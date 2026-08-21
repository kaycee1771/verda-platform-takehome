#!/usr/bin/env python3
"""Behavioral tests for the durable, effect-free Phase 6 broker store."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import shutil
import sys
import tempfile
import threading
import unittest
import uuid


ROOT = pathlib.Path(__file__).parents[2]
STORE_PATH = ROOT / "scripts/phase6/transaction-broker-store.py"
STORE_SPEC = importlib.util.spec_from_file_location("phase6_transaction_broker_store", STORE_PATH)
assert STORE_SPEC and STORE_SPEC.loader
STORE = importlib.util.module_from_spec(STORE_SPEC); STORE_SPEC.loader.exec_module(STORE)
BROKER_TEST_PATH = ROOT / "tests/static/test_phase6_transaction_broker_spec.py"
BROKER_SPEC = importlib.util.spec_from_file_location("phase6_broker_fixtures", BROKER_TEST_PATH)
assert BROKER_SPEC and BROKER_SPEC.loader
FIXTURES = importlib.util.module_from_spec(BROKER_SPEC); BROKER_SPEC.loader.exec_module(FIXTURES)
AUTH_TEST_PATH = ROOT / "tests/static/test_phase6_github_authorization.py"
AUTH_SPEC = importlib.util.spec_from_file_location("phase6_auth_fixtures", AUTH_TEST_PATH)
assert AUTH_SPEC and AUTH_SPEC.loader
AUTH_FIXTURES = importlib.util.module_from_spec(AUTH_SPEC); AUTH_SPEC.loader.exec_module(AUTH_FIXTURES)
NOW = FIXTURES.NOW


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def secure_probe(path: pathlib.Path) -> dict:
    status = path.lstat()
    return {"reparse": False, "nlink": status.st_nlink, "device": status.st_dev,
            "identity": status.st_ino, "owner_only": True}


@unittest.skipUnless(os.name == "nt", "protected broker store is deliberately Windows-only")
class DurableBrokerStoreTests(unittest.TestCase):
    def store(self, root: pathlib.Path, operation: str = FIXTURES.OPERATION, **kwargs):
        if "verifier" in kwargs:
            kwargs["allow_test_verifier"] = True
        return STORE.DurableBrokerStore(operation_id=operation, base=root,
                                        clock=lambda: NOW, security_probe=kwargs.pop("security_probe", secure_probe),
                                        **kwargs)

    def genesis(self, store, journal):
        return store.cas(journal, expected_generation=0, expected_lease_epoch=0,
                         expected_cas_nonce=None, expected_head_sha256=None)

    def adapter_store(self, root: pathlib.Path):
        store = self.store(root)
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text("{}", encoding="utf-8")
        return store

    def admission(self, root: pathlib.Path):
        mapping = {"broker": "broker_sha256", "policy": "transaction_policy_sha256",
                   "rollback_policy": "rollback_policy_sha256", "contract": "contract_sha256",
                   "tool_lock": "tool_lock_sha256", "security_review": "security_review_sha256",
                   "reliability_review": "reliability_review_sha256", "user_approval": "user_approval_sha256",
                   "plan": "plan_sha256", "pre_backup": "etcd_backup_sha256", "post_backup": "data_backup_sha256",
                   "preflight": "preflight_sha256", "cost": "cost_sha256", "capacity": "capacity_sha256",
                   "collector": "collector_sha256", "provider_facts": "provider_facts_sha256",
                   "journal": "journal_sha256"}
        artifact_root = root / "artifacts"; artifact_root.mkdir()
        artifacts = {}; authorization = AUTH_FIXTURES.artifact()
        for name, field in mapping.items():
            path = artifact_root / name; path.write_text(name, encoding="utf-8"); artifacts[name] = path
            authorization[field] = hashlib.sha256(name.encode()).hexdigest()
        state = {"state_lineage_sha256": authorization["state_lineage_sha256"], "state_serial": 12,
                 "canonical_state_path": str((root / "terraform" / "management.tfstate").resolve(strict=False)),
                 "raw_values_recorded": False}
        state_path = artifact_root / "state-receipt.json"
        state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        artifacts["state_receipt"] = state_path
        authorization_path = artifact_root / "authorization.json"
        authorization_path.write_text("  " + json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8")
        return artifacts, authorization, authorization_path

    def test_direct_entrypoint_refuses_and_has_no_effect_bodies(self) -> None:
        result = subprocess.run([sys.executable, str(STORE_PATH)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        source = STORE_PATH.read_text(encoding="utf-8")
        for forbidden in ("terraform apply", "ansible-playbook", "kubectl delete", "kubectl apply"):
            self.assertNotIn(forbidden, source)

    def test_phase2_mutex_name_and_wait_results_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); store = self.store(root)
            canonical = str((root / "terraform" / "management.tfstate").resolve(strict=False)).lower()
            self.assertEqual(store.state_mutex, f"Local\\VerdaPhase2State-{hashlib.sha256(canonical.encode()).hexdigest()}")
            mutex = STORE.NamedMutex("test")
            mutex._accept_wait_result(0x80); self.assertIs(mutex.abandoned, True)
            with self.assertRaisesRegex(STORE.StoreRefused, "another writer"):
                STORE.NamedMutex("test")._accept_wait_result(0x102)
            with self.assertRaisesRegex(STORE.StoreRefused, "wait failed"):
                STORE.NamedMutex("test")._accept_wait_result(0xFFFFFFFF)
        phase2 = (ROOT / "scripts/infra/phase2.ps1").read_text(encoding="utf-8")
        self.assertIn('$mutexName = "Local\\VerdaPhase2State-$stateDigest"', phase2)
        self.assertIn('"verda-phase6-locks-$uid"', phase2)
        self.assertIn("VerdaPhase2PosixLock]::flock", phase2)

    @unittest.skipIf(os.name == "nt", "POSIX directory-inode lock contract")
    def test_posix_lock_boundary_is_nonempty_directory_inode(self) -> None:
        name = "Local\\VerdaPhase2State-" + digest("shared-state")
        with STORE.NamedMutex(name):
            lockdir = pathlib.Path(tempfile.gettempdir()) / f"verda-phase6-locks-{os.getuid()}" / \
                f"verda-{STORE.digest_bytes(name.encode())}.lockdir"
            self.assertTrue((lockdir / ".boundary").is_file())
            with self.assertRaises(OSError):
                lockdir.rmdir()
            with self.assertRaisesRegex(STORE.StoreRefused, "another writer"):
                with STORE.NamedMutex(name):
                    pass

    def test_windows_security_and_handle_apis_are_explicitly_typed(self) -> None:
        source = STORE_PATH.read_text(encoding="utf-8")
        for marker in ("ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes",
                       "SetFileSecurityW.argtypes", "CreateMutexW.argtypes", "WaitForSingleObject.argtypes",
                       "GetFinalPathNameByHandleW.argtypes", "GetFileInformationByHandle.argtypes",
                       "ReadFile.argtypes", "MoveFileExW.argtypes"):
            self.assertIn(marker, source)
        self.assertIn("D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;GA;;;BA)", source)
        name = "Local\\VerdaPhase6Broker-" + digest("mutex-wrapper")
        with STORE.NamedMutex(name) as held:
            self.assertTrue(STORE._windows_mutex_handle_trusted(held.handle))
            outcomes = []
            def contender():
                try:
                    with STORE.NamedMutex(name): pass
                except STORE.StoreRefused as error:
                    outcomes.append(str(error))
            thread = threading.Thread(target=contender); thread.start(); thread.join()
            self.assertEqual(len(outcomes), 1)
            self.assertIn("another writer", outcomes[0])

    def test_windows_default_security_probe_refuses_untrusted_system_ancestor(self) -> None:
        base = pathlib.Path(os.environ["LOCALAPPDATA"]) / f"VerdaStoreProbe-{uuid.uuid4().hex}"
        try:
            store = STORE.DurableBrokerStore(operation_id=FIXTURES.OPERATION, base=base, clock=lambda: NOW)
            with self.assertRaisesRegex(STORE.StoreRefused, "system ancestor"):
                store.initialize()
        finally:
            shutil.rmtree(base, ignore_errors=True)

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

    def test_public_load_cannot_recover_active_paused_writer_temp(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); initial = FIXTURES.BrokerFixture(); self.genesis(self.store(root), initial.journal)
            initial.go({"event": "BEGIN_PREPARE", **initial.fake.gate("pre_prepare")})
            paused, release = threading.Event(), threading.Event()
            def hook(stage):
                if stage == "after_temp_fsync": paused.set(); release.wait(5)
            writer_store = self.store(root, crash_hook=hook); errors = []
            def writer():
                try:
                    writer_store.cas(initial.session.journal, expected_generation=1, expected_lease_epoch=1,
                                     expected_cas_nonce=initial.journal["cas_nonce"],
                                     expected_head_sha256=initial.journal["history"][-1]["entry_sha256"])
                except Exception as error: errors.append(error)
            thread = threading.Thread(target=writer); thread.start(); self.assertTrue(paused.wait(5))
            with self.assertRaisesRegex(STORE.StoreRefused, "another writer"):
                self.store(root).load()
            release.set(); thread.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(self.store(root).load()["generation"], 2)

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

    def test_orphan_temp_must_be_exact_genesis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); store = self.store(root); store.initialize()
            fixture = FIXTURES.BrokerFixture(); fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
            envelope = {"schema_version": 2, "operation_id": FIXTURES.OPERATION,
                        "journal": fixture.session.journal,
                        "nonces": [entry["cas_nonce"] for entry in fixture.session.journal["history"]]}
            store.temp_path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(STORE.StoreRefused, "START_SPEC genesis"):
                store.load()

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
            calls.append(command); return 0, json.dumps({"items": [{"metadata": {"name": "sensitive-host"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]}}]}), ""
        with tempfile.TemporaryDirectory() as folder:
            store = self.adapter_store(pathlib.Path(folder))
            adapter = STORE.ReadOnlyAdmissionAdapter(store, runner, lambda: NOW)
            receipt = adapter.collect("cluster-members")
        self.assertEqual(set(receipt), {"kind", "command_sha256", "started_at", "ended_at", "duration_ms",
                                        "freshness_seconds", "aggregate", "raw_values_recorded"})
        self.assertEqual(receipt["aggregate"], {"member_count": 1, "ready_count": 1})
        self.assertNotIn("sensitive-host", json.dumps(receipt))
        self.assertEqual(calls, [STORE.READ_ONLY_COMMANDS["cluster-members"]])
        with self.assertRaises(STORE.StoreRefused): adapter.collect("terraform-apply")

    def test_slow_read_only_collector_is_refused(self) -> None:
        times = iter((NOW, NOW + dt.timedelta(seconds=11)))
        with tempfile.TemporaryDirectory() as folder:
            adapter = STORE.ReadOnlyAdmissionAdapter(self.adapter_store(pathlib.Path(folder)),
                lambda _cmd: (0, '{"items":[]}', ""), lambda: next(times))
            with self.assertRaisesRegex(STORE.StoreRefused, "slow/stale"):
                adapter.collect("cluster-members")

    def test_real_kubernetes_ready_shape_and_reviewed_terraform_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.adapter_store(pathlib.Path(folder))
            malformed = STORE.ReadOnlyAdmissionAdapter(store,
                lambda _cmd: (0, '{"items":[{"status":{"conditions":[]}}]}', ""), lambda: NOW)
            with self.assertRaisesRegex(STORE.StoreRefused, "Ready condition"):
                malformed.collect("cluster-members")
            calls = []
            store.initialize()
            stale_digest = hashlib.sha256(b"{}").hexdigest()
            stale = store.root / f"state-{stale_digest}-{'a' * 32}.read-only.tfstate"
            stale.write_bytes(b"{}"); STORE._protect_windows_path(stale)
            stale_marker = stale.with_name(stale.name + ".manifest.json")
            stale_marker.write_text(json.dumps({"schema_version": 1, "operation_id": FIXTURES.OPERATION,
                "snapshot_name": stale.name, "snapshot_sha256": stale_digest,
                "state": "PLANNED",
                "created_at": "2026-08-21T12:00:00Z", "raw_values_recorded": False}), encoding="utf-8")
            STORE._protect_windows_path(stale_marker)
            adapter = STORE.ReadOnlyAdmissionAdapter(store,
                lambda command: (calls.append(command) or (0, '{"values":{"root_module":{"resources":[]}}}', "")),
                lambda: NOW)
            receipt = adapter.collect("terraform-state")
            self.assertNotEqual(calls[0][-1], str(store.state_path))
            self.assertEqual(receipt["canonical_state_path"], str(store.state_path))
            self.assertEqual(receipt["state_snapshot_sha256"], hashlib.sha256(b"{}").hexdigest())
            self.assertFalse(stale.exists()); self.assertFalse(stale_marker.exists())
            self.assertEqual(receipt["aggregate"], {"resource_count": 0})
            provider = STORE.ReadOnlyAdmissionAdapter(store,
                lambda _command: (0, '{"instances":[{"status":"running","instance_type":"CPU.8V.32G"},'
                                    '{"status":"stopped","instance_type":"CPU.8V.32G"}]}', ""), lambda: NOW)
            aggregate = provider.collect("provider-inventory")["aggregate"]
        self.assertEqual(aggregate["status_counts"], {"running": 1, "stopped": 1, "other": 0})
        self.assertEqual(aggregate["instance_type_counts"], {"CPU.8V.32G": 2})

    def test_admission_hashes_every_bound_artifact_and_calls_verifier_synchronously(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); artifacts, authorization, authorization_path = self.admission(root)
            calls = []
            def verifier(path, raw, auth):
                calls.append((path, raw, auth)); return {"status": "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT",
                                            "requires_reverification_before_use": True, "operation_id": FIXTURES.OPERATION,
                                            "authorization_sha256": STORE.digest_bytes(raw),
                                            "authorization_commit": "a" * 40,
                                            "authorization_history_sha256": digest("history"),
                                            "source_parent_commit": auth["source_parent_commit"],
                                            "workflow_id": auth["workflow_id"], "pr_number": auth["pr_number"],
                                            "complete_by": auth["complete_by"], "schema_version": 1, "phase": 6,
                                            "authorization_mode": "TRANSACTION", "web_flow_fingerprint": digest("web"),
                                            "raw_values_recorded": False}
            store = self.store(root, verifier=verifier)
            receipt = store.verify_admission(authorization_path=authorization_path, artifacts=artifacts)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][1].startswith(b"  {") and calls[0][1].endswith(b"\n"))
            authorization["plan_sha256"] = digest("wrong")
            authorization_path.write_text("  " + json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(STORE.StoreRefused, "plan hash"):
                store.verify_admission(authorization_path=authorization_path, artifacts=artifacts)

    def test_admission_artifact_identity_swap_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); artifacts, authorization, authorization_path = self.admission(root)
            calls = 0
            def swapping_probe(path):
                nonlocal calls
                facts = secure_probe(path)
                if path == artifacts["plan"]:
                    calls += 1
                    facts["identity"] += calls
                return facts
            verifier = lambda _path, raw, auth: {"status": "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT",
                                     "requires_reverification_before_use": True, "operation_id": FIXTURES.OPERATION,
                                     "authorization_sha256": STORE.digest_bytes(raw),
                                     "authorization_commit": "a" * 40,
                                     "authorization_history_sha256": digest("history"),
                                     "source_parent_commit": auth["source_parent_commit"],
                                     "workflow_id": auth["workflow_id"], "pr_number": auth["pr_number"],
                                     "complete_by": auth["complete_by"], "schema_version": 1, "phase": 6,
                                     "authorization_mode": "TRANSACTION", "web_flow_fingerprint": digest("web"),
                                     "raw_values_recorded": False}
            store = self.store(root, security_probe=swapping_probe, verifier=verifier)
            with self.assertRaisesRegex(STORE.StoreRefused, "identity changed"):
                store.verify_admission(authorization_path=authorization_path, artifacts=artifacts)


@unittest.skipIf(os.name == "nt", "non-Windows refusal contract")
class NonWindowsStoreRefusalTests(unittest.TestCase):
    def test_store_refuses_before_creating_or_reading_paths(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = pathlib.Path(folder) / "must-not-exist"
            with self.assertRaisesRegex(STORE.StoreRefused, "Windows-only"):
                STORE.DurableBrokerStore(operation_id=FIXTURES.OPERATION, base=base, clock=lambda: NOW)
            self.assertFalse(base.exists())


if __name__ == "__main__":
    unittest.main()
