#!/usr/bin/env python3
"""Dormant protected Phase 6 transaction broker execution boundary.

No public effect command exists in this module.  The checked-in contract is
inert; only the explicit test factory can install a fake private child.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any, Callable


HERE = pathlib.Path(__file__).resolve().parent
STORE_SPEC = importlib.util.spec_from_file_location("phase6_broker_store", HERE / "transaction-broker-store.py")
assert STORE_SPEC and STORE_SPEC.loader
STORE = importlib.util.module_from_spec(STORE_SPEC); STORE_SPEC.loader.exec_module(STORE)

INERT_CONTRACT = {"schema_version": 1, "phase": 6, "status": "DORMANT",
                  "execution_enabled": False, "production_adapter_present": False,
                  "public_execution_route_present": False, "raw_values_recorded": False}
RECEIPT_KEYS = {"schema_version", "operation_id", "action", "journal_sha256", "effect_sha256",
                "state_lineage_sha256", "state_serial", "started_at", "ended_at", "raw_values_recorded"}
_PRIVATE_CAPABILITY = object()


class BrokerRefused(RuntimeError):
    pass


def refuse(message: str) -> None:
    raise BrokerRefused(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class _PrivatePhase2Child:
    """Non-exported in-process channel; subclasses are accepted only in tests."""
    def _invoke(self, capability: object, action: str, request: dict[str, Any]) -> dict[str, Any]:
        if capability is not _PRIVATE_CAPABILITY:
            refuse("private Phase 2 child capability differs")
        raise NotImplementedError


class ProtectedTransactionBroker:
    def __init__(self, *, store: Any, verifier: Any, child: _PrivatePhase2Child,
                 reducer: Callable[[dict[str, Any], str], dict[str, Any]], test_only: bool = False) -> None:
        if not test_only:
            refuse("checked-in Phase 6 execution contract is inert")
        self.store, self.verifier, self.child, self.reducer = store, verifier, child, reducer

    @classmethod
    def _for_tests(cls, **kwargs: Any) -> "ProtectedTransactionBroker":
        return cls(test_only=True, **kwargs)

    @classmethod
    def from_checked_in_contract(cls, *, contract: dict[str, Any], **_: Any) -> "ProtectedTransactionBroker":
        if contract != INERT_CONTRACT or contract["execution_enabled"] is not True:
            refuse("checked-in Phase 6 execution contract is inert")
        refuse("production Phase 6 effect adapter is absent")

    def transact(self, *, action: str, authorization_path: pathlib.Path,
                 artifacts: dict[str, pathlib.Path], journal: dict[str, Any],
                 expected_generation: int, expected_lease_epoch: int,
                 expected_cas_nonce: str | None, expected_head_sha256: str | None) -> dict[str, Any]:
        if action not in {"prepare", "apply", "recover", "postflight", "rollback"}:
            refuse("private transaction action differs")
        with self.store.locked():
            admission = self.store.verify_admission(authorization_path=authorization_path, artifacts=artifacts)
            if admission.get("operation_id") != self.store.operation_id:
                refuse("transaction authorization operation differs")
            candidate = self.reducer(journal, action)
            self.store.cas(candidate, expected_generation=expected_generation,
                           expected_lease_epoch=expected_lease_epoch,
                           expected_cas_nonce=expected_cas_nonce,
                           expected_head_sha256=expected_head_sha256)
            request = {"operation_id": self.store.operation_id, "action": action,
                       "journal_sha256": hashlib.sha256(canonical_bytes(candidate)).hexdigest(),
                       "authorization_receipt_sha256": hashlib.sha256(canonical_bytes(admission)).hexdigest(),
                       "raw_values_recorded": False}
            receipt = self.child._invoke(_PRIVATE_CAPABILITY, action, request)
            if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS
                    or receipt.get("operation_id") != self.store.operation_id
                    or receipt.get("action") != action or receipt.get("journal_sha256") != request["journal_sha256"]
                    or receipt.get("raw_values_recorded") is not False):
                refuse("private Phase 2 child receipt differs")
            return receipt


def main() -> int:
    print("REFUSED: checked-in Phase 6 transaction execution contract is inert", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
