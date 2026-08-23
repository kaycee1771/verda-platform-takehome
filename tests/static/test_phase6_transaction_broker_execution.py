#!/usr/bin/env python3
import hashlib,importlib.util,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
P=load("pure_protocol",ROOT/"scripts/phase6/transaction-broker.py")
F=load("protocol_fixtures",ROOT/"tests/static/test_phase6_transaction_broker_spec.py")
S=load("protocol_store",ROOT/"scripts/phase6/transaction-broker-store.py")
PATH=ROOT/"scripts/phase6/transaction-broker.py"
def h(x): return hashlib.sha256(x.encode()).hexdigest()
def admission(j):
 return {k:j[k] for k in ("operation_id","authorization_sha256","authorization_history_sha256","verifier_receipt_sha256","broker_sha256","policy_sha256","rollback_policy_sha256","lease_id","lease_epoch")}|{"fencing_token":P.digest({"intent_entry_sha256":j["history"][-1]["entry_sha256"],"lease_id":j["lease_id"],"lease_epoch":j["lease_epoch"]}),"verified_at":j["updated_at"],"raw_values_recorded":False}
def receipt(j,action,classification,evidence):
 serial=j["state_serial_before"]
 if action=="apply" and classification=="COMPLETE": serial+=1
 elif action in {"recover","postflight","rollback"} and j.get("state_serial_after") is not None: serial=j["state_serial_after"]
 return {"schema_version":1,"operation_id":j["operation_id"],"action":action,"intent_entry_sha256":j["history"][-1]["entry_sha256"],"authorization_sha256":j["authorization_sha256"],"authorization_history_sha256":j["authorization_history_sha256"],"lease_id":j["lease_id"],"lease_epoch":j["lease_epoch"],"fencing_token":j["pending_fencing_token"],"observed_at":"2026-08-21T12:00:01Z","probe_fresh":True,"probe_outcome":classification,"state_lineage_sha256":j["state_lineage_sha256"],"state_serial":serial,"gate_sha256":j["latest_gate_sha256"],"evidence_sha256":P.digest(evidence),"classification":classification,"event_evidence":evidence,"mode":"LIVE","raw_values_recorded":False}
class CanonicalProtocolTests(unittest.TestCase):
 def test_no_effect_surface(self):
  self.assertEqual(subprocess.run([sys.executable,str(PATH)],capture_output=True).returncode,64)
  src=PATH.read_text()
  for x in ("protocol_events","_invoke","transact(","subprocess","terraform","ansible","kubectl","open("): self.assertNotIn(x,src)
 def test_real_store_prepare_intent_outcome_and_tamper(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d)
   def probe(p): st=p.lstat(); return {"reparse":False,"nlink":st.st_nlink,"device":st.st_dev,"identity":st.st_ino,"owner_only":True}
   store=S.DurableBrokerStore(operation_id=F.OPERATION,base=root,clock=lambda:F.NOW,security_probe=probe,allow_test_security_probe=True)
   f=F.BrokerFixture(); store.cas(f.journal,expected_generation=0,expected_lease_epoch=0,expected_cas_nonce=None,expected_head_sha256=None)
   old=f.session.journal
   event=P.TransactionProtocol.canonical_intent(journal=old,action="prepare",admission=admission(old),evidence=f.fake.gate("pre_prepare"))
   f.go(event); intent=f.session.journal; S.MODEL.validate_journal(intent)
   store.cas(intent,expected_generation=old["generation"],expected_lease_epoch=old["lease_epoch"],expected_cas_nonce=old["cas_nonce"],expected_head_sha256=old["history"][-1]["entry_sha256"])
   persisted=store.load()
   self.assertEqual((persisted["pending_fencing_token"],persisted["pending_admission_sha256"]),
                    (admission(old)["fencing_token"],P.digest(admission(old))))
   evidence={"prepare_receipt_sha256":f.fake.receipt("prepare")}; r=receipt(intent,"prepare","COMPLETE",evidence)
   event=P.TransactionProtocol.canonical_outcome(journal=intent,receipt=r); f.go(event); outcome=f.session.journal
   store.cas(outcome,expected_generation=intent["generation"],expected_lease_epoch=intent["lease_epoch"],expected_cas_nonce=intent["cas_nonce"],expected_head_sha256=intent["history"][-1]["entry_sha256"])
   self.assertEqual(store.load()["state"],"PREPARED")
   self.assertIsNone(store.load()["pending_fencing_token"])
   r["lease_epoch"]-=1
   with self.assertRaises(P.ProtocolRefused): P.TransactionProtocol.canonical_outcome(journal=intent,receipt=r)
   evil=admission(old)
   with self.assertRaisesRegex(P.ProtocolRefused,"select event"):
    P.TransactionProtocol.canonical_intent(journal=old,action="prepare",admission=evil,
      evidence={**f.fake.gate("pre_prepare"),"event":"APPLY_SUCCEEDED"})
   replay=receipt(intent,"prepare","COMPLETE",evidence); replay["intent_entry_sha256"]=old["history"][-1]["entry_sha256"]
   with self.assertRaisesRegex(P.ProtocolRefused,"cross-intent"):
    P.TransactionProtocol.canonical_outcome(journal=intent,receipt=replay)
 def test_absence_never_not_started_and_zero_drift(self):
  f=F.BrokerFixture(); f.prepare(); f.apply(); f.begin_recovery(); f.recovery_milestones()
  f.go({"event":"RECOVERY_SUCCEEDED","recovery_receipt_sha256":F.digest("recovered"),"exact_effects_verified":True})
  f.go({"event":"BEGIN_POSTFLIGHT",**f.fake.gate("postflight")})
  with self.assertRaises(P.ProtocolRefused): P.TransactionProtocol.canonical_outcome(journal=f.session.journal,receipt={})
  r=receipt(f.session.journal,"postflight","COMPLETE",{"postflight_sha256":h("p"),"rollback_required":False,"zero_drift":False})
  with self.assertRaisesRegex(P.ProtocolRefused,"zero drift"): P.TransactionProtocol.canonical_outcome(journal=f.session.journal,receipt=r)
 def test_apply_adoption_emits_reducer_input_and_replays(self):
  f=F.BrokerFixture(); f.prepare()
  old=f.session.journal
  intent=P.TransactionProtocol.canonical_intent(journal=old,action="apply",admission=admission(old),
                                                 evidence=f.fake.gate("pre_apply_two_survivor"))
  f.go(intent); pending=f.session.journal
  evidence={"probe_sha256":h("apply-none"),"state_backup_sha256":F.backup("adopt-original",12),
            "exact_target_state":False,"zero_drift":False,"state_lineage_sha256":pending["state_lineage_sha256"],
            "state_serial_after":None}
  r=receipt(pending,"apply","NOT_STARTED",evidence); r["mode"]="ADOPTION"
  event=P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r)
  self.assertEqual((event["event"],event["outcome"]),("ADOPT_APPLY","NOT_STARTED"))
  restored=f.go(event)
  self.assertEqual(restored["state"],"PREPARED")
  S.MODEL.validate_journal(restored)
 def test_canonical_uncertain_adoptions_terminalize_and_no_effect_reverts(self):
  f=F.BrokerFixture(); f.prepare(); f.apply(); f.begin_recovery()
  reverted=f.go({"event":"ADOPT_RECOVERY_NOT_STARTED","probe_sha256":h("probe"),"exact_no_effect":True})
  self.assertEqual(reverted["state"],"APPLIED")
  for action in ("recovery","postflight"):
   for outcome in ("PARTIAL","UNKNOWN"):
    q=F.BrokerFixture(); q.prepare(); q.apply(); q.begin_recovery()
    if action=="postflight":
     q.recovery_milestones(); q.go({"event":"RECOVERY_SUCCEEDED","recovery_receipt_sha256":h("recovered"),"exact_effects_verified":True})
     q.go({"event":"BEGIN_POSTFLIGHT",**q.fake.gate("postflight")})
    terminal=q.go({"event":f"ADOPT_{action.upper()}_{outcome}","probe_sha256":h("probe"),
                   "current_state_receipt_sha256":h("current")})
    self.assertEqual((terminal["state"],terminal["manual_intervention_required"],terminal["rollback_required"]),
                     ("FAILED_SAFE",True,False))
  q=F.BrokerFixture(); q.prepare(); q.apply(); q.begin_rollback()
  self.assertEqual(q.session.journal["rollback_origin_state"],"APPLIED")
  restored=q.go({"event":"ADOPT_ROLLBACK_NOT_STARTED","probe_sha256":h("rollback-none"),"exact_no_effect":True})
  self.assertEqual((restored["state"],restored["rollback_origin_state"],restored["rollback_milestone"]),
                   ("APPLIED",None,"NONE"))
if __name__=="__main__": unittest.main()
