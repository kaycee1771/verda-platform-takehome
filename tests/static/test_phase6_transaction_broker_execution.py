#!/usr/bin/env python3
import hashlib, importlib.util, pathlib, subprocess, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).parents[2]; PATH=ROOT/"scripts/phase6/transaction-broker.py"
SPEC=importlib.util.spec_from_file_location("phase6_pure_protocol", PATH); P=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(P)
FIXTURE_PATH=ROOT/"tests/static/test_phase6_transaction_broker_spec.py"
FS=importlib.util.spec_from_file_location("phase6_protocol_fixture",FIXTURE_PATH); F=importlib.util.module_from_spec(FS); FS.loader.exec_module(F)
STORE_PATH=ROOT/"scripts/phase6/transaction-broker-store.py"
SS=importlib.util.spec_from_file_location("phase6_protocol_store",STORE_PATH); S=importlib.util.module_from_spec(SS); SS.loader.exec_module(S)
OP="a"*64
def h(x): return hashlib.sha256(x.encode()).hexdigest()

class PureProtocolTests(unittest.TestCase):
 def setUp(self):
  self.j={"operation_id":OP,"generation":1,"lease_epoch":7,"cas_nonce":h("old"),"pending_action":None,"protocol_events":[]}
  self.a={"operation_id":OP,"authorization_sha256":h("auth"),"binding_sha256":h("binding"),"verified_at":"2026-08-21T12:00:00Z","raw_values_recorded":False}
 def intent(self, action="apply"):
  return P.TransactionProtocol.intent(journal=self.j,action=action,admission=self.a,lease_id=h("lease"),lease_epoch=7,fencing_token=h("fence"),cas_nonce=h("intent"))
 def receipt(self,i,a):
  r={"schema_version":1,"operation_id":OP,"action":a,"intent_sha256":P.digest(i),"authorization_sha256":h("auth"),"lease_id":h("lease"),"lease_epoch":7,"fencing_token":h("fence"),"started_at":"2026-08-21T12:00:00Z","ended_at":"2026-08-21T12:00:01Z","state_lineage_sha256":h("lineage"),"state_serial":12,"gate_sha256":h("gate"),"evidence_sha256":h("evidence"),"outcome":"COMPLETE","raw_values_recorded":False}
  for k in P.EVIDENCE[a]: r[k]=False if k=="zero_drift" else ("M1" if k.endswith("milestone") else h(k))
  return r
 def test_direct_import_has_no_effect_capability(self):
  self.assertEqual(subprocess.run([sys.executable,str(PATH)],capture_output=True).returncode,64)
  source=PATH.read_text()
  for word in ("_for_tests","test_only","_invoke","transact(","subprocess","terraform","ansible","kubectl","open("):
   self.assertNotIn(word,source)
 def test_two_cas_candidates_all_actions(self):
  for a in P.ACTIONS:
   i=self.intent(a); self.assertEqual((i["generation"],i["protocol_events"][-1]["kind"]),(2,"INTENT"))
   o=P.TransactionProtocol.outcome(intent=i,receipt=self.receipt(i,a),cas_nonce=h("out"))
   self.assertEqual((o["generation"],o["protocol_events"][-1]["kind"]),(3,"OUTCOME"))
 def test_stale_tamper_crash_adoption(self):
  with self.assertRaises(P.ProtocolRefused): P.TransactionProtocol.intent(journal=self.j,action="apply",admission=self.a,lease_id=h("l"),lease_epoch=8,fencing_token=h("f"),cas_nonce=h("n"))
  i=self.intent(); r=self.receipt(i,"apply"); r["fencing_token"]=h("stale")
  with self.assertRaises(P.ProtocolRefused): P.TransactionProtocol.outcome(intent=i,receipt=r,cas_nonce=h("o"))
  self.assertEqual(P.TransactionProtocol.adoption(None),"NOT_STARTED")
  for value in P.ADOPTION: self.assertEqual(P.TransactionProtocol.adoption({"outcome":value}),value)
 def test_canonical_intent_and_outcome_persist_through_real_store_model(self):
  with tempfile.TemporaryDirectory() as folder:
   root=pathlib.Path(folder)
   def probe(path):
    st=path.lstat(); return {"reparse":False,"nlink":st.st_nlink,"device":st.st_dev,"identity":st.st_ino,"owner_only":True}
   store=S.DurableBrokerStore(operation_id=F.OPERATION,base=root,clock=lambda:F.NOW,
       security_probe=probe,allow_test_security_probe=True)
   fixture=F.BrokerFixture(); store.cas(fixture.journal,expected_generation=0,expected_lease_epoch=0,
       expected_cas_nonce=None,expected_head_sha256=None)
   old=fixture.session.journal
   fixture.go(P.TransactionProtocol.canonical_intent("prepare",fixture.fake.gate("pre_prepare")))
   intent=fixture.session.journal; S.MODEL.validate_journal(intent)
   store.cas(intent,expected_generation=old["generation"],expected_lease_epoch=old["lease_epoch"],
       expected_cas_nonce=old["cas_nonce"],expected_head_sha256=old["history"][-1]["entry_sha256"])
   before=fixture.session.journal
   fixture.go(P.TransactionProtocol.canonical_outcome("prepare","COMPLETE",
       {"prepare_receipt_sha256":fixture.fake.receipt("prepare")}))
   outcome=fixture.session.journal; S.MODEL.validate_journal(outcome)
   store.cas(outcome,expected_generation=before["generation"],expected_lease_epoch=before["lease_epoch"],
       expected_cas_nonce=before["cas_nonce"],expected_head_sha256=before["history"][-1]["entry_sha256"])
   self.assertEqual(store.load()["state"],"PREPARED")
if __name__=="__main__": unittest.main()
