#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[2]
PATH = ROOT / "scripts/phase6/transaction-broker.py"
SPEC = importlib.util.spec_from_file_location("phase6_execution_boundary", PATH)
assert SPEC and SPEC.loader
BROKER = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(BROKER)
OPERATION = "a" * 64


class FakeStore:
    operation_id = OPERATION
    def __init__(self): self.events = []
    @contextlib.contextmanager
    def locked(self):
        self.events.append("lock"); yield; self.events.append("unlock")
    def verify_admission(self, **_): self.events.append("verify"); return {"operation_id": OPERATION}
    def cas(self, journal, **_): self.events.append(("cas", journal["action"]))


class FakeChild(BROKER._PrivatePhase2Child):
    def __init__(self, events): self.events = events
    def _invoke(self, capability, action, request):
        super_call = capability is BROKER._PRIVATE_CAPABILITY
        if not super_call: raise AssertionError("capability")
        self.events.append(("effect", action))
        return {"schema_version": 1, "operation_id": OPERATION, "action": action,
                "journal_sha256": request["journal_sha256"], "effect_sha256": hashlib.sha256(action.encode()).hexdigest(),
                "state_lineage_sha256": "b" * 64, "state_serial": 12,
                "started_at": "2026-08-21T12:00:00Z", "ended_at": "2026-08-21T12:00:01Z",
                "raw_values_recorded": False}


class BrokerExecutionBoundaryTests(unittest.TestCase):
    def test_entrypoint_and_production_factory_refuse(self):
        result = subprocess.run([sys.executable, str(PATH)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        with self.assertRaisesRegex(BROKER.BrokerRefused, "inert"):
            BROKER.ProtectedTransactionBroker.from_checked_in_contract(contract=BROKER.INERT_CONTRACT)

    def test_private_lifecycle_is_lock_verify_cas_effect_ordered(self):
        store = FakeStore(); child = FakeChild(store.events)
        broker = BROKER.ProtectedTransactionBroker._for_tests(
            store=store, verifier=object(), child=child,
            reducer=lambda journal, action: {**journal, "action": action})
        journal = {"generation": 1}
        for action in ("prepare", "apply", "recover", "postflight", "rollback"):
            receipt = broker.transact(action=action, authorization_path=pathlib.Path("unused"), artifacts={},
                journal=journal, expected_generation=1, expected_lease_epoch=1,
                expected_cas_nonce="c" * 64, expected_head_sha256="d" * 64)
            self.assertFalse(receipt["raw_values_recorded"])
        for index in range(0, len(store.events), 5):
            self.assertEqual(store.events[index:index + 5],
                ["lock", "verify", ("cas", ("prepare", "apply", "recover", "postflight", "rollback")[index // 5]),
                 ("effect", ("prepare", "apply", "recover", "postflight", "rollback")[index // 5]), "unlock"])

    def test_private_capability_and_receipt_shape_refuse(self):
        child = FakeChild([])
        with self.assertRaisesRegex(BROKER.BrokerRefused, "capability"):
            BROKER._PrivatePhase2Child()._invoke(object(), "apply", {})
        source = PATH.read_text(encoding="utf-8")
        for forbidden in ("subprocess", "terraform apply", "ansible-playbook", "kubectl apply"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__": unittest.main()
