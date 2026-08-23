#!/usr/bin/env python3
import copy,datetime as dt,hashlib,importlib.util,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
P=load("pure_protocol",ROOT/"scripts/phase6/transaction-broker.py")
_intent=P.TransactionProtocol.canonical_intent; _outcome=P.TransactionProtocol.canonical_outcome
P.TransactionProtocol.canonical_intent=staticmethod(lambda trusted_transition_time="2026-08-21T12:00:00Z",**kw:
 _intent(trusted_transition_time=trusted_transition_time,**kw))
P.TransactionProtocol.canonical_outcome=staticmethod(lambda trusted_transition_time="2026-08-21T12:00:01Z",**kw:
 _outcome(trusted_transition_time=trusted_transition_time,**kw))
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
 if action=="rollback" and classification=="COMPLETE": serial=j["state_serial_before"]
 return {"schema_version":1,"operation_id":j["operation_id"],"action":action,"intent_entry_sha256":j["history"][-1]["entry_sha256"],"authorization_sha256":j["authorization_sha256"],"authorization_history_sha256":j["authorization_history_sha256"],"lease_id":j["lease_id"],"lease_epoch":j["lease_epoch"],"fencing_token":j["pending_fencing_token"],"observed_at":"2026-08-21T12:00:01Z","probe_fresh":True,"probe_outcome":classification,"state_lineage_sha256":j["state_lineage_sha256"],"state_serial":serial,"gate_sha256":j["latest_gate_sha256"],"evidence_sha256":P.digest(evidence),"classification":classification,"event_evidence":evidence,"mode":"LIVE","raw_values_recorded":False}
class CanonicalProtocolTests(unittest.TestCase):
 def _store(self,root):
  def probe(p): st=p.lstat(); return {"reparse":False,"nlink":st.st_nlink,"device":st.st_dev,"identity":st.st_ino,"owner_only":True}
  return S.DurableBrokerStore(operation_id=F.OPERATION,base=root,clock=lambda:F.NOW,security_probe=probe,allow_test_security_probe=True)
 def _cas(self,store,old,new):
  store.cas(new,expected_generation=old["generation"],expected_lease_epoch=old["lease_epoch"],
            expected_cas_nonce=old["cas_nonce"],expected_head_sha256=old["history"][-1]["entry_sha256"])
 def _event(self,store,f,event):
  old=f.session.journal; f.go(event); self._cas(store,old,f.session.journal)
 def _applied(self,store,f):
  for event in ({"event":"BEGIN_PREPARE",**f.fake.gate("pre_prepare")},
                {"event":"PREPARE_SUCCEEDED","prepare_receipt_sha256":h("prepare")},
                {"event":"BEGIN_APPLY",**f.fake.gate("pre_apply_two_survivor")},
                {"event":"APPLY_SUCCEEDED","phase2_receipt_sha256":h("phase2"),
                 "state_backup_sha256":F.backup("state",12),"pre_apply_backup_sha256":F.backup("pre",12),
                 "post_apply_backup_sha256":F.backup("post",13),"state_lineage_sha256":f.authorization["state_lineage_sha256"],
                 "state_serial_before":12,"state_serial_after":13}): self._event(store,f,event)
 def _recovered(self,store,f):
  current=f.session.journal
  self._event(store,f,{"event":"BEGIN_RECOVERY",**f.fake.gate("pre_recovery_two_survivor"),
    "inventory_sha256":h("inventory"),"known_hosts_sha256":h("hosts"),
    "applied_state_receipt_sha256":current["apply_receipt_sha256"]})
  for milestone in S.MODEL.RECOVERY_MILESTONES[1:]:
   self._event(store,f,{"event":"RECOVERY_MILESTONE","milestone":milestone,"receipt_sha256":h("r-"+milestone),
    "effect_probe_sha256":h("p-"+milestone),"exact_effect_verified":True})
  self._event(store,f,{"event":"RECOVERY_SUCCEEDED","recovery_receipt_sha256":h("recovered"),"exact_effects_verified":True})
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
 def test_real_store_recovery_adoption_classification_matrix(self):
  expected={"COMPLETE":"RECOVERED","NOT_STARTED":"APPLIED","PARTIAL":"FAILED_SAFE","UNKNOWN":"FAILED_SAFE"}
  for classification in expected:
   with self.subTest(classification=classification), tempfile.TemporaryDirectory() as d:
    f=F.BrokerFixture(); store=self._store(pathlib.Path(d))
    store.cas(f.session.journal,expected_generation=0,expected_lease_epoch=0,
              expected_cas_nonce=None,expected_head_sha256=None)
    self._applied(store,f)
    old=f.session.journal
    intent=P.TransactionProtocol.canonical_intent(journal=old,action="recover",admission=admission(old),
      evidence={**f.fake.gate("pre_recovery_two_survivor"),"inventory_sha256":h("inventory"),
       "known_hosts_sha256":h("hosts"),"applied_state_receipt_sha256":old["apply_receipt_sha256"]})
    f.go(intent); pending=f.session.journal; self._cas(store,old,pending)
    if classification=="COMPLETE":
     for milestone in S.MODEL.RECOVERY_MILESTONES[1:]:
      prior=f.session.journal
      f.go({"event":"RECOVERY_MILESTONE","milestone":milestone,"receipt_sha256":h("r-"+milestone),
            "effect_probe_sha256":h("p-"+milestone),"exact_effect_verified":True})
      self._cas(store,prior,f.session.journal)
     pending=f.session.journal
     evidence={"recovery_receipt_sha256":h("recovered"),"exact_effects_verified":True}
    elif classification=="NOT_STARTED": evidence={"probe_sha256":h("none"),"exact_no_effect":True}
    else: evidence={"probe_sha256":h("probe"),"current_state_receipt_sha256":h("current")}
    r=receipt(pending,"recover",classification,evidence); r["mode"]="ADOPTION"
    event=P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r)
    prior=f.session.journal; f.go(event); self._cas(store,prior,f.session.journal)
    loaded=store.load(); S.MODEL.validate_journal(loaded)
    self.assertEqual(loaded["state"],expected[classification])
    self.assertIsNone(loaded["pending_fencing_token"])
 def test_real_store_postflight_matrix(self):
  cases=(("LIVE","COMPLETE","COMPLETED"),("ADOPTION","COMPLETE","COMPLETED"),
         ("ADOPTION","NOT_STARTED","RECOVERED"),("ADOPTION","PARTIAL","FAILED_SAFE"),
         ("ADOPTION","UNKNOWN","FAILED_SAFE"))
  for mode,classification,target in cases:
   with self.subTest(mode=mode,classification=classification), tempfile.TemporaryDirectory() as d:
    f=F.BrokerFixture(); store=self._store(pathlib.Path(d)); store.cas(f.session.journal,expected_generation=0,
      expected_lease_epoch=0,expected_cas_nonce=None,expected_head_sha256=None)
    self._applied(store,f); self._recovered(store,f); old=f.session.journal
    intent=P.TransactionProtocol.canonical_intent(journal=old,action="postflight",admission=admission(old),
                                                   evidence=f.fake.gate("postflight"))
    self._event(store,f,intent); pending=f.session.journal
    if classification=="COMPLETE": evidence={"postflight_sha256":h("postflight"),"zero_drift":True,"capacity_verified":True}
    elif classification=="NOT_STARTED": evidence={"probe_sha256":h("none"),"exact_no_effect":True}
    else: evidence={"probe_sha256":h("probe"),"current_state_receipt_sha256":h("current")}
    r=receipt(pending,"postflight",classification,evidence); r["mode"]=mode
    self._event(store,f,P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r))
    loaded=store.load(); S.MODEL.validate_journal(loaded); self.assertEqual(loaded["state"],target)
 def test_real_store_rollback_matrix(self):
  cases=(("LIVE","COMPLETE","ROLLED_BACK"),("ADOPTION","COMPLETE","ROLLED_BACK"),
         ("ADOPTION","NOT_STARTED","APPLIED"),("ADOPTION","PARTIAL","FAILED_SAFE"),
         ("ADOPTION","UNKNOWN","FAILED_SAFE"))
  for mode,classification,target in cases:
   with self.subTest(mode=mode,classification=classification), tempfile.TemporaryDirectory() as d:
    f=F.BrokerFixture(); store=self._store(pathlib.Path(d)); store.cas(f.session.journal,expected_generation=0,
      expected_lease_epoch=0,expected_cas_nonce=None,expected_head_sha256=None); self._applied(store,f)
    old=f.session.journal
    intent=P.TransactionProtocol.canonical_intent(journal=old,action="rollback",admission=admission(old),evidence={
      **f.fake.gate("rollback_two_survivor"),"inventory_sha256":h("rb-inventory"),"known_hosts_sha256":h("rb-hosts"),
      "state_backup_sha256":old["state_backup_sha256"],"applied_state_receipt_sha256":old["apply_receipt_sha256"],
      "rollback_plan_sha256":h("rb-plan"),"rollback_plan_semantic_sha256":h("rb-semantic"),
      "current_state_receipt_sha256":h("rb-current"),"current_state_lineage_sha256":old["state_lineage_sha256"],
      "current_state_serial":old["state_serial_after"],"pre_rollback_backup_sha256":F.backup("rb-pre",13)})
    self._event(store,f,intent); pending=f.session.journal
    if classification=="COMPLETE":
     for milestone in S.MODEL.ROLLBACK_MILESTONES[2:]: self._event(store,f,{"event":"ROLLBACK_MILESTONE",
      "milestone":milestone,"receipt_sha256":h("rr-"+milestone),"effect_probe_sha256":h("rp-"+milestone),
      "exact_effect_verified":True})
     pending=f.session.journal; evidence={"rollback_receipt_sha256":h("rolled"),
     "post_rollback_backup_sha256":F.backup("rb-post",12),"exact_effects_verified":True,"zero_drift":True}
    elif classification=="NOT_STARTED": evidence={"probe_sha256":h("none"),"exact_no_effect":True}
    else: evidence={"probe_sha256":h("probe"),"current_state_receipt_sha256":h("current"),
                    "current_state_lineage_sha256":pending["state_lineage_sha256"],"current_state_serial":13,
                    "reconciled_rollback_state_backup":F.backup("rb-reconciled-"+classification,13)}
    r=receipt(pending,"rollback",classification,evidence); r["mode"]=mode
    self._event(store,f,P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r))
    loaded=store.load(); S.MODEL.validate_journal(loaded); self.assertEqual(loaded["state"],target)
 def test_shared_protocol_tamper_table_leaves_store_head_unchanged(self):
  with tempfile.TemporaryDirectory() as d:
   f=F.BrokerFixture(); store=self._store(pathlib.Path(d)); store.cas(f.session.journal,expected_generation=0,
    expected_lease_epoch=0,expected_cas_nonce=None,expected_head_sha256=None)
   old=f.session.journal; intent=P.TransactionProtocol.canonical_intent(journal=old,action="prepare",
    admission=admission(old),evidence=f.fake.gate("pre_prepare")); self._event(store,f,intent); pending=f.session.journal
   evidence={"prepare_receipt_sha256":h("prepared")}; good=receipt(pending,"prepare","COMPLETE",evidence)
   head=(store.load()["generation"],store.load()["history"][-1]["entry_sha256"])
   mutations={
    "fence":lambda r:r.__setitem__("fencing_token",h("bad-fence")),
    "epoch":lambda r:r.__setitem__("lease_epoch",r["lease_epoch"]+1),
    "auth":lambda r:r.__setitem__("authorization_sha256",h("bad-auth")),
    "time":lambda r:r.__setitem__("observed_at","2026-08-21T11:59:59Z"),
    "serial":lambda r:r.__setitem__("state_serial",r["state_serial"]+1),
    "gate":lambda r:r.__setitem__("gate_sha256",h("bad-gate")),
    "evidence":lambda r:r.__setitem__("evidence_sha256",h("bad-evidence")),
    "intent":lambda r:r.__setitem__("intent_entry_sha256",h("bad-intent")),
    "illegal_mode":lambda r:r.__setitem__("mode","SIDELOAD"),
    "illegal_class":lambda r:r.__setitem__("classification","SKIPPED"),
    "non_bool_fresh":lambda r:r.__setitem__("probe_fresh",1),
   }
   for label,mutate in mutations.items():
    with self.subTest(label=label):
     bad=copy.deepcopy(good); mutate(bad)
     with self.assertRaises(P.ProtocolRefused): P.TransactionProtocol.canonical_outcome(journal=pending,receipt=bad)
     self.assertEqual((store.load()["generation"],store.load()["history"][-1]["entry_sha256"]),head)
   event=P.TransactionProtocol.canonical_outcome(journal=pending,receipt=good); prior=f.session.journal; f.go(event)
   with self.assertRaises(S.StoreRefused):
    store.cas(f.session.journal,expected_generation=prior["generation"],expected_lease_epoch=prior["lease_epoch"],
     expected_cas_nonce=h("bad-nonce"),expected_head_sha256=prior["history"][-1]["entry_sha256"])
   self.assertEqual((store.load()["generation"],store.load()["history"][-1]["entry_sha256"]),head)
 def test_trusted_transition_clock_rejects_unchanged_stale_evidence(self):
  f=F.BrokerFixture(); old=f.session.journal
  with self.assertRaisesRegex(P.ProtocolRefused,"stale"):
   P.TransactionProtocol.canonical_intent(journal=old,action="prepare",admission=admission(old),
    evidence=f.fake.gate("pre_prepare"),trusted_transition_time="2026-08-21T13:00:00Z")
  intent=P.TransactionProtocol.canonical_intent(journal=old,action="prepare",admission=admission(old),
   evidence=f.fake.gate("pre_prepare")); f.go(intent); pending=f.session.journal
  evidence={"prepare_receipt_sha256":h("prepared")}; r=receipt(pending,"prepare","COMPLETE",evidence)
  with self.assertRaisesRegex(P.ProtocolRefused,"stale"):
   P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r,trusted_transition_time="2026-08-21T13:00:00Z")
  event=P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r)
  with self.assertRaisesRegex(F.MODEL.BrokerRefused,"stale"):
   f.go(event,dt.datetime(2026,8,21,13,0,tzinfo=dt.timezone.utc))
 def test_rollback_not_started_restores_each_durable_origin(self):
  for origin in ("APPLIED","RECOVERING","RECOVERED","POSTFLIGHT","ROLLBACK_REQUIRED"):
   with self.subTest(origin=origin), tempfile.TemporaryDirectory() as d:
    f=F.BrokerFixture(); store=self._store(pathlib.Path(d)); store.cas(f.session.journal,expected_generation=0,
     expected_lease_epoch=0,expected_cas_nonce=None,expected_head_sha256=None); self._applied(store,f)
    if origin in {"RECOVERING","ROLLBACK_REQUIRED"}:
     current=f.session.journal; self._event(store,f,{"event":"BEGIN_RECOVERY",**f.fake.gate("pre_recovery_two_survivor"),
      "inventory_sha256":h("i"),"known_hosts_sha256":h("k"),"applied_state_receipt_sha256":current["apply_receipt_sha256"]})
     if origin=="ROLLBACK_REQUIRED": self._event(store,f,{"event":"FAIL_RECOVERY_UNSAFE","failure_receipt_sha256":h("unsafe")})
    elif origin in {"RECOVERED","POSTFLIGHT"}:
     self._recovered(store,f)
     if origin=="POSTFLIGHT": self._event(store,f,{"event":"BEGIN_POSTFLIGHT",**f.fake.gate("postflight")})
    old=f.session.journal; intent=P.TransactionProtocol.canonical_intent(journal=old,action="rollback",admission=admission(old),evidence={
     **f.fake.gate("rollback_two_survivor"),"inventory_sha256":h("ri"),"known_hosts_sha256":h("rk"),
     "state_backup_sha256":old["state_backup_sha256"],"applied_state_receipt_sha256":old["apply_receipt_sha256"],
     "rollback_plan_sha256":h("plan"),"rollback_plan_semantic_sha256":h("semantic"),
     "current_state_receipt_sha256":h("current"),"current_state_lineage_sha256":old["state_lineage_sha256"],
     "current_state_serial":old["state_serial_after"],"pre_rollback_backup_sha256":F.backup("origin-pre-"+origin,13)})
    self._event(store,f,intent); pending=f.session.journal
    evidence={"probe_sha256":h("none"),"exact_no_effect":True}; r=receipt(pending,"rollback","NOT_STARTED",evidence); r["mode"]="ADOPTION"
    self._event(store,f,P.TransactionProtocol.canonical_outcome(journal=pending,receipt=r))
    self.assertEqual(store.load()["state"],origin)
if __name__=="__main__": unittest.main()
