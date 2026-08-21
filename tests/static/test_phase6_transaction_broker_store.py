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

    def genesis(self, store, journal):
        return store.cas(journal, expected_generation=0, expected_lease_epoch=0,
                         expected_cas_nonce=None, expected_head_sha256=None)

    def test_direct_entrypoint_refuses_and_has_no_effect_bodies(self) -> None:
        result = subprocess.run([sys.executable, str(STORE_PATH)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        source = STORE_PATH.read_text(encoding="utf-8")
        for forbidden in ("terraform apply", "ansible-playbook", "kubectl delete", "kubectl apply"):
            self.assertNotIn(forbidden, source)

    def test_atomic_cas_load_nonce_replay_and_stale_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(pathlib.Path(folder)); fixture = FIXTURES.BrokerFixture()
            receipt = self.genesis(store, fixture.journal)
            self.assertEqual(receipt["generation"], 1)
            self.assertEqual(store.load(), fixture.journal)
            with self.assertRaisesRegex(STORE.StoreRefused, "forks|advance"):
                store.cas(fixture.journal, expected_generation=1, expected_lease_epoch=1,
                          expected_cas_nonce=fixture.journal["cas_nonce"],
                          expected_head_sha256=fixture.journal["history"][-1]["entry_sha256"])
            fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            with self.assertRaisesRegex(STORE.StoreRefused, "stale"):
                store.cas(fixture.session.journal, expected_generation=1, expected_lease_epoch=0,
                          expected_cas_nonce=fixture.journal["cas_nonce"],
                          expected_head_sha256=fixture.journal["history"][-1]["entry_sha256"])

    def test_concurrent_writers_have_one_cas_winner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(pathlib.Path(folder)); fixture = FIXTURES.BrokerFixture()
            self.genesis(store, fixture.journal)
            fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            candidate = fixture.session.journal; outcomes: list[str] = []
            def writer() -> None:
                try:
                    store.cas(copy.deepcopy(candidate), expected_generation=1, expected_lease_epoch=1,
                              expected_cas_nonce=fixture.journal["cas_nonce"],
                              expected_head_sha256=fixture.journal["history"][-1]["entry_sha256"])
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
            self.genesis(store, fixture.journal)
            replacement = FIXTURES.FakeLease(digest("replacement-lease")); replacement.epoch = 2
            adopted = store.adopt_read_only(policy=FIXTURES.POLICY, lease=replacement,
                                            boundary=FIXTURES.boundary(fixture.journal),
                                            nonce_source=fixture.nonces)
            self.assertEqual(adopted["history"][-1]["event"], "ADOPT_LEASE")
            self.assertEqual(adopted["lease_epoch"], 2)
            self.assertEqual(store.load(), adopted)

    def test_non_genesis_and_forked_history_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); fixture = FIXTURES.BrokerFixture()
            fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            with self.assertRaisesRegex(STORE.StoreRefused, "START_SPEC genesis"):
                self.genesis(self.store(root), fixture.session.journal)
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); first = FIXTURES.BrokerFixture(); original = copy.deepcopy(first.journal)
            store = self.store(root); self.genesis(store, original)
            first.go({"event": "BEGIN_PREPARE", **first.fake.gate("pre_prepare")})
            store.cas(first.session.journal, expected_generation=1, expected_lease_epoch=1,
                      expected_cas_nonce=original["cas_nonce"], expected_head_sha256=original["history"][-1]["entry_sha256"])
            alternate = FIXTURES.BrokerFixture()
            late = dt.datetime(2026, 8, 21, 16, 30, tzinfo=dt.timezone.utc)
            alternate.go({"event": "BEGIN_PREPARE", **alternate.fake.gate("pre_prepare", late)}, now=late)
            current = store.load()
            with self.assertRaisesRegex(STORE.StoreRefused, "forks"):
                store.cas(alternate.session.journal, expected_generation=current["generation"],
                          expected_lease_epoch=current["lease_epoch"], expected_cas_nonce=current["cas_nonce"],
                          expected_head_sha256=current["history"][-1]["entry_sha256"])

    def test_atomic_envelope_recovers_each_injected_crash_boundary(self) -> None:
        for stage in ("after_temp_fsync", "after_replace", "after_directory_fsync"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                fired = []
                def crash(point):
                    if point == stage and not fired:
                        fired.append(point); raise RuntimeError("injected crash")
                fixture = FIXTURES.BrokerFixture(); root = pathlib.Path(folder)
                with self.assertRaises(RuntimeError):
                    self.genesis(self.store(root, crash_hook=crash), fixture.journal)
                recovered = self.store(root).load()
                self.assertEqual(recovered, fixture.journal)
                self.assertFalse((root / "phase6-resize-control" /
                                  f"broker-{FIXTURES.OPERATION}.envelope-v2.tmp").exists())

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
            calls.append(command); return 0, json.dumps({"items": [{"name": "sensitive-host", "ready": True}]}), ""
        adapter = STORE.ReadOnlyAdmissionAdapter(runner, lambda: NOW)
        receipt = adapter.collect("cluster-members")
        self.assertEqual(set(receipt), {"kind", "command_sha256", "started_at", "ended_at", "duration_ms",
                                        "freshness_seconds", "aggregate", "raw_values_recorded"})
        self.assertEqual(receipt["aggregate"], {"member_count": 1, "ready_count": 1})
        self.assertNotIn("sensitive-host", json.dumps(receipt))
        self.assertEqual(calls, [STORE.READ_ONLY_COMMANDS["cluster-members"]])
        with self.assertRaises(STORE.StoreRefused): adapter.collect("terraform-apply")

    def test_slow_read_only_collector_is_refused(self) -> None:
        times = iter((NOW, NOW + dt.timedelta(seconds=11)))
        adapter = STORE.ReadOnlyAdmissionAdapter(lambda _cmd: (0, '{"items":[]}', ""), lambda: next(times))
        with self.assertRaisesRegex(STORE.StoreRefused, "slow/stale"):
            adapter.collect("cluster-members")

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
                calls.append(auth); return {"requires_reverification_before_use": True,
                                            "operation_id": FIXTURES.OPERATION,
                                            "artifact_hashes": expected}
            store = self.store(root, verifier=verifier)
            authorization = {"operation_id": FIXTURES.OPERATION, "artifact_hashes": expected}
            receipt = store.verify_admission(authorization=authorization, artifacts=artifacts)
            self.assertEqual(receipt["measured_hashes"], expected)
            self.assertEqual(len(calls), 1)
            expected["plan"] = digest("wrong")
            with self.assertRaisesRegex(STORE.StoreRefused, "plan hash"):
                store.verify_admission(authorization=authorization, artifacts=artifacts)

    def test_admission_artifact_identity_swap_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); artifact_root = root / "artifacts"; artifact_root.mkdir()
            names = {"broker", "policy", "rollback_policy", "contract", "tool_lock", "review",
                     "plan", "state", "pre_backup", "post_backup"}
            artifacts = {}
            for name in names:
                path = artifact_root / name; path.write_text(name, encoding="utf-8"); artifacts[name] = path
            expected = {name: hashlib.sha256(name.encode()).hexdigest() for name in names}
            calls = 0
            def swapping_probe(path):
                nonlocal calls
                facts = secure_probe(path)
                if path == artifacts["plan"]:
                    calls += 1
                    facts["identity"] += calls
                return facts
            verifier = lambda _auth: {"requires_reverification_before_use": True,
                                      "operation_id": FIXTURES.OPERATION, "artifact_hashes": expected}
            store = self.store(root, security_probe=swapping_probe, verifier=verifier)
            with self.assertRaisesRegex(STORE.StoreRefused, "identity changed"):
                store.verify_admission(authorization={"operation_id": FIXTURES.OPERATION,
                                                      "artifact_hashes": expected}, artifacts=artifacts)


if __name__ == "__main__":
    unittest.main()
