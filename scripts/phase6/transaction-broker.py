#!/usr/bin/env python3
"""Dormant pure Phase 6 two-CAS protocol. No effect implementation lives here."""
from __future__ import annotations
import datetime as dt, hashlib, json, re, sys
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
 "event_evidence","mode","raw_values_recorded"}

class ProtocolRefused(ValueError): pass
def refuse(message: str) -> None: raise ProtocolRefused(message)
def canonical(value: Any) -> bytes: return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def digest(value: Any) -> str: return hashlib.sha256(canonical(value)).hexdigest()
HEX64=re.compile(r"^[0-9a-f]{64}$")
def timestamp(value: Any) -> dt.datetime:
 try:
  if not isinstance(value,str) or not value.endswith("Z"): raise ValueError
  return dt.datetime.fromisoformat(value[:-1]+"+00:00")
 except (ValueError,TypeError): refuse("receipt timestamp differs")

class TransactionProtocol:
 @staticmethod
 def canonical_intent(*, journal: dict[str,Any], action: str, admission: dict[str,Any],
                      evidence: dict[str, Any], trusted_transition_time: str) -> dict[str, Any]:
  names={"prepare":"BEGIN_PREPARE","apply":"BEGIN_APPLY","recover":"BEGIN_RECOVERY",
         "postflight":"BEGIN_POSTFLIGHT","rollback":"BEGIN_ROLLBACK"}
  allowed=INTENT_STATES.get(action)
  if action not in names or not isinstance(evidence,dict) or \
     journal.get("state") not in ({allowed} if isinstance(allowed,str) else allowed): refuse("canonical intent state differs")
  if set(admission)!=ADMISSION_KEYS or admission["raw_values_recorded"] is not False: refuse("admission schema differs")
  if type(admission["lease_epoch"]) is not int or admission["lease_epoch"] < 1 or type(admission["verified_at"]) is not str:
   refuse("admission scalar types differ")
  for key in ("operation_id","authorization_sha256","authorization_history_sha256","verifier_receipt_sha256",
              "broker_sha256","policy_sha256","rollback_policy_sha256","lease_id","lease_epoch"):
   if admission[key]!=journal[key]: refuse("admission journal/fence differs")
  for key in ("operation_id","authorization_sha256","authorization_history_sha256","verifier_receipt_sha256",
              "broker_sha256","policy_sha256","rollback_policy_sha256","lease_id","fencing_token"):
   if not isinstance(admission[key],str) or not HEX64.fullmatch(admission[key]): refuse("admission digest differs")
  verified=timestamp(admission["verified_at"]); trusted=timestamp(trusted_transition_time)
  if verified > trusted or (trusted-verified).total_seconds()>30: refuse("admission verification is stale or future-dated")
  expected_fence=digest({"intent_entry_sha256":journal["history"][-1]["entry_sha256"],
                         "lease_id":journal["lease_id"],"lease_epoch":journal["lease_epoch"]})
  if admission["fencing_token"]!=expected_fence: refuse("admission fencing token differs")
  if "event" in evidence: refuse("caller evidence cannot select event")
  return {**evidence,"fencing_token":admission["fencing_token"],"pending_admission_verified_at":admission["verified_at"],
          "admission_sha256":digest(admission),"event":names[action]}

 @staticmethod
 def canonical_outcome(*, journal: dict[str,Any], receipt: dict[str,Any], trusted_transition_time: str) -> dict[str, Any]:
  complete={"prepare":"PREPARE_SUCCEEDED","apply":"APPLY_SUCCEEDED","recover":"RECOVERY_SUCCEEDED",
            "postflight":"POSTFLIGHT_SUCCEEDED","rollback":"ROLLBACK_SUCCEEDED"}
  if not isinstance(receipt,dict) or set(receipt)!=RECEIPT_KEYS or type(receipt.get("schema_version")) is not int \
     or receipt.get("schema_version")!=1 \
     or receipt.get("raw_values_recorded") is not False: refuse("outcome receipt schema differs")
  action=receipt.get("action"); outcome=receipt.get("classification"); evidence=receipt.get("event_evidence")
  if action not in complete or outcome not in ADOPTION or not isinstance(evidence,dict) \
     or journal.get("state")!=PENDING_STATES[action]: refuse("canonical outcome state differs")
  if (type(action) is not str or type(outcome) is not str or type(receipt["mode"]) is not str
      or type(receipt["probe_outcome"]) is not str or type(receipt["observed_at"]) is not str
      or type(receipt["lease_epoch"]) is not int or receipt["lease_epoch"] < 1):
   refuse("outcome scalar types differ")
  if "event" in evidence: refuse("caller evidence cannot select event")
  for key in ("operation_id","authorization_sha256","authorization_history_sha256","lease_id","lease_epoch",
              "state_lineage_sha256"):
   expected=journal["state_lineage_sha256"] if key=="state_lineage_sha256" else journal[key]
   if receipt[key]!=expected: refuse("outcome receipt journal/fence differs")
  if receipt["intent_entry_sha256"]!=journal["history"][-1]["entry_sha256"]: refuse("cross-intent receipt replay differs")
  if (receipt["fencing_token"] != journal.get("pending_fencing_token")
      or journal.get("pending_admission_sha256") is None): refuse("outcome persisted admission fence differs")
  for key in ("intent_entry_sha256","authorization_sha256","authorization_history_sha256","fencing_token",
              "state_lineage_sha256","gate_sha256","evidence_sha256"):
   if not isinstance(receipt[key],str) or not HEX64.fullmatch(receipt[key]): refuse("outcome digest differs")
  observed=timestamp(receipt["observed_at"]); intent_time=timestamp(journal["history"][-1]["captured_at"])
  trusted=timestamp(trusted_transition_time)
  if observed < intent_time or observed > trusted or (trusted-observed).total_seconds()>30:
   refuse("outcome receipt is stale")
  if receipt["evidence_sha256"]!=digest(evidence): refuse("outcome evidence digest differs")
  if receipt["gate_sha256"]!=journal["latest_gate_sha256"] or type(receipt["state_serial"]) is not int \
     or receipt["state_serial"]<journal["state_serial_before"]: refuse("outcome state/gate relation differs")
  if type(receipt["probe_fresh"]) is not bool or receipt["probe_fresh"] is not True or receipt["probe_outcome"]!=outcome:
   refuse("outcome requires fresh exact probe")
  before=journal["state_serial_before"]; serial=receipt["state_serial"]
  if action in {"prepare","recover","postflight"} and serial != (journal.get("state_serial_after") or before):
   refuse("outcome serial changed outside provider apply")
  if action=="apply" and outcome=="COMPLETE" and (serial <= before or evidence.get("state_serial_after") != serial):
   refuse("apply receipt/evidence serial differs")
  if action=="apply" and outcome=="COMPLETE":
   post=evidence.get("post_apply_backup_sha256")
   if not isinstance(post,dict) or post.get("state_serial")!=serial: refuse("apply post-backup serial differs")
  if action=="apply" and outcome=="NOT_STARTED" and serial != before: refuse("apply no-effect serial differs")
  if action=="apply" and outcome in {"PARTIAL","UNKNOWN"} and evidence.get("current_state_serial") != serial:
   refuse("apply uncertain current-state serial differs")
  if action=="rollback" and outcome=="NOT_STARTED" and serial != journal["state_serial_after"]:
   refuse("rollback no-effect serial differs")
  if action=="rollback" and outcome=="COMPLETE":
   backup=evidence.get("post_rollback_backup_sha256")
   if not isinstance(backup,dict) or backup.get("state_serial")!=serial or serial!=before:
    refuse("rollback restored-state serial differs")
  if action=="rollback" and outcome in {"PARTIAL","UNKNOWN"} and evidence.get("current_state_serial") != serial:
   refuse("rollback uncertain current-state serial differs")
  if outcome=="COMPLETE" and action in {"postflight","rollback"} and evidence.get("zero_drift") is not True:
   refuse("terminal complete requires zero drift")
  if receipt["mode"] not in {"LIVE","ADOPTION"}: refuse("outcome receipt mode differs")
  if outcome != "COMPLETE" and receipt["mode"] != "ADOPTION":
   refuse("non-complete classification requires adoption mode")
  if action=="apply" and receipt["mode"]=="ADOPTION":
   return {**evidence,"outcome":outcome,"receipt_observed_at":receipt["observed_at"],"fencing_token":journal["pending_fencing_token"],
           "admission_sha256":journal["pending_admission_sha256"],"event":"ADOPT_APPLY"}
  stem="RECOVERY" if action=="recover" else action.upper()
  if outcome=="COMPLETE" and receipt["mode"]=="LIVE": name=complete[action]
  elif outcome=="COMPLETE": name=f"ADOPT_{stem}_COMPLETE"
  elif outcome=="NOT_STARTED": name=f"ADOPT_{stem}_NOT_STARTED"
  elif outcome in {"PARTIAL","UNKNOWN"}: name=f"ADOPT_{stem}_{outcome}"
  else: refuse("canonical outcome requires a fresh supported adoption transition")
  return {**evidence,"receipt_observed_at":receipt["observed_at"],"fencing_token":journal["pending_fencing_token"],
          "admission_sha256":journal["pending_admission_sha256"],"event":name}

def main() -> int:
 print("REFUSED: dormant Phase 6 protocol contains no effect adapter", file=sys.stderr); return 64
if __name__ == "__main__": raise SystemExit(main())
