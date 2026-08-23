#!/usr/bin/env python3
"""Dormant pure Phase 6 two-CAS protocol. No effect implementation lives here."""
from __future__ import annotations
import hashlib, json, sys
from typing import Any

ACTIONS = {"prepare", "apply", "recover", "postflight", "rollback"}
ADOPTION = {"NOT_STARTED", "COMPLETE", "PARTIAL", "UNKNOWN"}
INTENT_STATES={"prepare":"AUTHORIZED","apply":"PREPARED","recover":"APPLIED",
 "postflight":"RECOVERED","rollback":{"APPLIED","RECOVERING","RECOVERED","POSTFLIGHT","ROLLBACK_REQUIRED"}}
PENDING_STATES={"prepare":"PREPARING","apply":"APPLYING","recover":"RECOVERING",
 "postflight":"POSTFLIGHT","rollback":"ROLLING_BACK"}
ADMISSION_KEYS={"operation_id","authorization_sha256","authorization_history_sha256","verifier_receipt_sha256",
 "broker_sha256","policy_sha256","rollback_policy_sha256","lease_id","lease_epoch","fencing_token",
 "verified_at","raw_values_recorded"}
RECEIPT_KEYS={"schema_version","operation_id","action","intent_entry_sha256","authorization_sha256",
 "authorization_history_sha256","lease_id","lease_epoch","fencing_token","observed_at","probe_fresh",
 "probe_outcome","state_lineage_sha256","state_serial","gate_sha256","evidence_sha256","classification",
 "event_evidence","raw_values_recorded"}

class ProtocolRefused(ValueError): pass
def refuse(message: str) -> None: raise ProtocolRefused(message)
def canonical(value: Any) -> bytes: return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def digest(value: Any) -> str: return hashlib.sha256(canonical(value)).hexdigest()

class TransactionProtocol:
 @staticmethod
 def canonical_intent(*, journal: dict[str,Any], action: str, admission: dict[str,Any],
                      evidence: dict[str, Any]) -> dict[str, Any]:
  names={"prepare":"BEGIN_PREPARE","apply":"BEGIN_APPLY","recover":"BEGIN_RECOVERY",
         "postflight":"BEGIN_POSTFLIGHT","rollback":"BEGIN_ROLLBACK"}
  allowed=INTENT_STATES.get(action)
  if action not in names or not isinstance(evidence,dict) or \
     journal.get("state") not in ({allowed} if isinstance(allowed,str) else allowed): refuse("canonical intent state differs")
  if set(admission)!=ADMISSION_KEYS or admission["raw_values_recorded"] is not False: refuse("admission schema differs")
  for key in ("operation_id","authorization_sha256","authorization_history_sha256","verifier_receipt_sha256",
              "broker_sha256","policy_sha256","rollback_policy_sha256","lease_id","lease_epoch"):
   if admission[key]!=journal[key]: refuse("admission journal/fence differs")
  return {"event":names[action], **evidence}

 @staticmethod
 def canonical_outcome(*, journal: dict[str,Any], receipt: dict[str,Any]) -> dict[str, Any]:
  complete={"prepare":"PREPARE_SUCCEEDED","apply":"APPLY_SUCCEEDED","recover":"RECOVERY_SUCCEEDED",
            "postflight":"POSTFLIGHT_SUCCEEDED","rollback":"ROLLBACK_SUCCEEDED"}
  if set(receipt)!=RECEIPT_KEYS or receipt.get("raw_values_recorded") is not False: refuse("outcome receipt schema differs")
  action=receipt.get("action"); outcome=receipt.get("classification"); evidence=receipt.get("event_evidence")
  if action not in complete or outcome not in ADOPTION or not isinstance(evidence,dict) \
     or journal.get("state")!=PENDING_STATES[action]: refuse("canonical outcome state differs")
  for key in ("operation_id","authorization_sha256","authorization_history_sha256","lease_id","lease_epoch",
              "state_lineage_sha256"):
   expected=journal["state_lineage_sha256"] if key=="state_lineage_sha256" else journal[key]
   if receipt[key]!=expected: refuse("outcome receipt journal/fence differs")
  if not receipt["probe_fresh"] or receipt["probe_outcome"]!=outcome or not receipt["observed_at"].endswith("Z"):
   refuse("outcome requires fresh exact probe")
  if outcome=="COMPLETE" and action in {"postflight","rollback"} and evidence.get("zero_drift") is not True:
   refuse("terminal complete requires zero drift")
  if outcome=="COMPLETE": name=complete[action]
  elif outcome=="NOT_STARTED": name=f"ADOPT_{action.upper()}_NOT_STARTED"
  elif outcome in {"PARTIAL","UNKNOWN"} and action in {"prepare","apply"}:
   name=f"ADOPT_{action.upper()}_{outcome}"
  else: refuse("canonical outcome requires a fresh supported adoption transition")
  return {"event":name, **evidence}

def main() -> int:
 print("REFUSED: dormant Phase 6 protocol contains no effect adapter", file=sys.stderr); return 64
if __name__ == "__main__": raise SystemExit(main())
