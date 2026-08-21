#!/usr/bin/env python3
"""Behavioral tests for the durable, effect-free Phase 6 broker store."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = pathlib.Path(__file__).parents[2]
STORE_PATH = ROOT / "scripts/phase6/transaction-broker-store.py"
STORE_SPEC = importlib.util.spec_from_file_location("phase6_transaction_broker_store", STORE_PATH)
assert STORE_SPEC and STORE_SPEC.loader
STORE = importlib.util.module_from_spec(STORE_SPEC); STORE_SPEC.loader.exec_module(STORE)
BROKER_TEST_PATH = ROOT / "tests/static/test_phase6_transaction_broker_spec.py"
BROKER_SPEC = importlib.util.spec_from_file_location("phase6_broker_fixtures", BROKER_TEST_PATH)
assert BROKER_SPEC and BROKER_SPEC.loader
FIXTURES = importlib.util.module_from_spec(BROKER_SPEC); BROKER_SPEC.loader.exec_module(FIXTURES)
NOW = FIXTURES.NOW


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def secure_probe(path: pathlib.Path) -> dict:
    status = path.lstat()
    return {"reparse": False, "nlink": status.st_nlink, "device": status.st_dev,
            "identity": status.st_ino, "owner_only": True}


class DurableBrokerStoreTests(unittest.TestCase):
    def store(self, root: pathlib.Path, operation: str = FIXTURES.OPERATION, **kwargs):
        return STORE.DurableBrokerStore(operation_id=operation, base=root,
                                        clock=lambda: NOW, security_probe=kwargs.pop("security_probe", secure_probe),
                                        **kwargs)

    def test_direct_entrypoint_refuses_and_has_no_effect_bodies(self) -> None:
        result = subprocess.run([sys.executable, str(STORE_PATH)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        source = STORE_PATH.read_text(encoding="utf-8")
        for forbidden in ("terraform apply", "ansible-playbook", "kubectl delete", "kubectl apply"):
            self.assertNotIn(forbidden, source)

    def test_atomic_cas_load_nonce_replay_and_stale_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(pathlib.Path(folder)); fixture = FIXTURES.BrokerFixture()
            receipt = store.cas(fixture.journal, expected_generation=0, expected_lease_epoch=0)
            self.assertEqual(receipt["generation"], 1)
            self.assertEqual(store.load(), fixture.journal)
            with self.assertRaisesRegex(STORE.StoreRefused, "nonce replayed"):
                store.cas(fixture.journal, expected_generation=1, expected_lease_epoch=1)
            fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            with self.assertRaisesRegex(STORE.StoreRefused, "stale"):
                store.cas(fixture.session.journal, expected_generation=1, expected_lease_epoch=0)

    def test_concurrent_writers_have_one_cas_winner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(pathlib.Path(folder)); fixture = FIXTURES.BrokerFixture()
            store.cas(fixture.journal, expected_generation=0, expected_lease_epoch=0)
            fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            candidate = fixture.session.journal; outcomes: list[str] = []
            def writer() -> None:
                try:
                    store.cas(copy.deepcopy(candidate), expected_generation=1, expected_lease_epoch=1)
                    outcomes.append("won")
                except STORE.StoreRefused:
                    outcomes.append("refused")
            threads = [threading.Thread(target=writer) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(sorted(outcomes), ["refused", "won"])

    def test_crash_reacquire_persists_only_read_only_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(pathlib.Path(folder)); fixture = FIXTURES.BrokerFixture()
            store.cas(fixture.journal, expected_generation=0, expected_lease_epoch=0)
            replacement = FIXTURES.FakeLease(digest("replacement-lease")); replacement.epoch = 2
            adopted = store.adopt_read_only(policy=FIXTURES.POLICY, lease=replacement,
                                            boundary=FIXTURES.boundary(fixture.journal),
                                            nonce_source=fixture.nonces)
            self.assertEqual(adopted["history"][-1]["event"], "ADOPT_LEASE")
            self.assertEqual(adopted["lease_epoch"], 2)
            self.assertEqual(store.load(), adopted)

    def test_torn_write_reparse_alias_and_hardlink_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); store = self.store(root); store.initialize()
            store.temp_path.write_text("{torn", encoding="utf-8")
            with self.assertRaisesRegex(STORE.StoreRefused, "torn"):
                store.load()
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            def hostile(path: pathlib.Path) -> dict:
                facts = secure_probe(path)
                if path.name == "phase6-resize-control": facts["reparse"] = True
                return facts
            with self.assertRaisesRegex(STORE.StoreRefused, "reparse"):
                self.store(root, security_probe=hostile).initialize()

    def test_read_only_adapter_is_fixed_and_returns_only_sanitized_shape(self) -> None:
        calls: list[tuple[str, ...]] = []
        def runner(command: tuple[str, ...]):
            calls.append(command); return 0, json.dumps({"items": [{"name": "sensitive-host"}]}), ""
        adapter = STORE.ReadOnlyAdmissionAdapter(runner, lambda: NOW)
        receipt = adapter.collect("cluster-members")
        self.assertEqual(set(receipt), {"kind", "shape_sha256", "observed_at", "raw_values_recorded"})
        self.assertNotIn("sensitive-host", json.dumps(receipt))
        self.assertEqual(calls, [STORE.READ_ONLY_COMMANDS["cluster-members"]])
        with self.assertRaises(STORE.StoreRefused): adapter.collect("terraform-apply")

    def test_admission_hashes_every_bound_artifact_and_calls_verifier_synchronously(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); artifact_root = root / "artifacts"; artifact_root.mkdir()
            names = {"broker", "policy", "rollback_policy", "contract", "tool_lock", "review",
                     "plan", "state", "pre_backup", "post_backup"}
            artifacts = {}
            for name in names:
                path = artifact_root / name; path.write_text(name, encoding="utf-8"); artifacts[name] = path
            expected = {name: hashlib.sha256(name.encode()).hexdigest() for name in names}
            calls = []
            def verifier(auth):
                calls.append(auth); return {"requires_reverification_before_use": True}
            store = self.store(root, verifier=verifier)
            receipt = store.verify_admission(authorization={"operation_id": FIXTURES.OPERATION},
                                             artifacts=artifacts, expected_hashes=expected)
            self.assertEqual(receipt["measured_hashes"], expected)
            self.assertEqual(len(calls), 1)
            expected["plan"] = digest("wrong")
            with self.assertRaisesRegex(STORE.StoreRefused, "plan hash"):
                store.verify_admission(authorization={}, artifacts=artifacts, expected_hashes=expected)


if __name__ == "__main__":
    unittest.main()
