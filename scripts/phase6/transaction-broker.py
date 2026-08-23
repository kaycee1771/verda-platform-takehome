#!/usr/bin/env python3
"""Dormant pure Phase 6 two-CAS protocol. No effect implementation lives here."""
from __future__ import annotations
import hashlib, json, sys
from typing import Any

ACTIONS = {"prepare", "apply", "recover", "postflight", "rollback"}
ADOPTION = {"NOT_STARTED", "COMPLETE", "PARTIAL", "UNKNOWN"}
EVIDENCE = {
 "prepare": {"pre_backup_sha256", "prepare_receipt_sha256"},
 "apply": {"plan_sha256", "plan_semantic_sha256", "pre_backup_sha256", "post_backup_sha256"},
 "recover": {"recovery_milestone", "recovery_receipt_sha256", "post_backup_sha256"},
 "postflight": {"postflight_receipt_sha256", "zero_drift"},
 "rollback": {"rollback_plan_sha256", "rollback_milestone", "pre_backup_sha256", "post_backup_sha256", "zero_drift"}}
COMMON = {"schema_version", "operation_id", "action", "intent_sha256", "authorization_sha256",
 "lease_id", "lease_epoch", "fencing_token", "started_at", "ended_at", "state_lineage_sha256",
 "state_serial", "gate_sha256", "evidence_sha256", "outcome", "raw_values_recorded"}

class ProtocolRefused(ValueError): pass
def refuse(message: str) -> None: raise ProtocolRefused(message)
def canonical(value: Any) -> bytes: return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def digest(value: Any) -> str: return hashlib.sha256(canonical(value)).hexdigest()

class TransactionProtocol:
 @staticmethod
 def intent(*, journal: dict[str, Any], action: str, admission: dict[str, Any], lease_id: str,
            lease_epoch: int, fencing_token: str, cas_nonce: str) -> dict[str, Any]:
  if action not in ACTIONS: refuse("action differs")
  if set(admission) != {"operation_id", "authorization_sha256", "binding_sha256", "verified_at", "raw_values_recorded"} \
     or admission["raw_values_recorded"] is not False: refuse("admission differs")
  if journal.get("operation_id") != admission["operation_id"] or journal.get("lease_epoch") != lease_epoch \
     or journal.get("pending_action") is not None: refuse("journal fence differs")
  event = {"kind":"INTENT", "action":action, "authorization_sha256":admission["authorization_sha256"],
   "binding_sha256":admission["binding_sha256"], "lease_id":lease_id, "lease_epoch":lease_epoch,
   "fencing_token":fencing_token, "raw_values_recorded":False}
  return {**journal, "generation":journal["generation"]+1, "cas_nonce":cas_nonce,
   "pending_action":action, "protocol_events":[*journal.get("protocol_events", []), event]}

 @staticmethod
 def outcome(*, intent: dict[str, Any], receipt: dict[str, Any], cas_nonce: str) -> dict[str, Any]:
  action = intent.get("pending_action"); prior = intent.get("protocol_events", [{}])[-1]
  if action not in ACTIONS or set(receipt) != COMMON | EVIDENCE[action] or receipt.get("schema_version") != 1 \
     or receipt.get("operation_id") != intent.get("operation_id") or receipt.get("action") != action \
     or receipt.get("intent_sha256") != digest(intent) or receipt.get("lease_epoch") != intent.get("lease_epoch") \
     or receipt.get("lease_id") != prior.get("lease_id") or receipt.get("fencing_token") != prior.get("fencing_token") \
     or receipt.get("authorization_sha256") != prior.get("authorization_sha256") \
     or receipt.get("outcome") not in ADOPTION or receipt.get("raw_values_recorded") is not False:
   refuse("effect receipt differs")
  event={"kind":"OUTCOME", "action":action, "outcome":receipt["outcome"],
         "receipt_sha256":digest(receipt), "raw_values_recorded":False}
  return {**intent, "generation":intent["generation"]+1, "cas_nonce":cas_nonce, "pending_action":None,
          "protocol_events":[*intent["protocol_events"], event]}

 @staticmethod
 def adoption(receipt: dict[str, Any] | None) -> str:
  if receipt is None: return "NOT_STARTED"
  if receipt.get("outcome") not in ADOPTION: refuse("adoption differs")
  return receipt["outcome"]

def main() -> int:
 print("REFUSED: dormant Phase 6 protocol contains no effect adapter", file=sys.stderr); return 64
if __name__ == "__main__": raise SystemExit(main())
