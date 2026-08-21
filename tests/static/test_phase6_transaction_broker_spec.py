#!/usr/bin/env python3
"""Pure behavioral tests for the dormant Phase 6 transaction broker model."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

import jsonschema


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/phase6/transaction-broker-model.py"
SPEC = importlib.util.spec_from_file_location("phase6_transaction_broker_model", SCRIPT)
assert SPEC and SPEC.loader
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)
POLICY = json.loads((ROOT / "config/phase6-transaction-broker-policy.json").read_text())
ROLLBACK_POLICY = json.loads((ROOT / "config/phase6-transaction-rollback-policy.json").read_text())
NOW = dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.timezone.utc)
OPERATION = "0" * 64


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class Nonces:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return digest(f"cas-{self.value}")


class FakeLease:
    def __init__(self, lease_id: str = digest("lease-1")) -> None:
        self.operation_id = OPERATION
        self.lease_id = lease_id
        self.epoch = 1
        self.held = True

    def release_and_reacquire(self) -> None:
        self.held = False
        self.epoch += 1
        self.held = True


class FakeTranscriptAdapter:
    """Builds evidence dictionaries only; it has no command or mutation method."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def gate(self, kind: str, now: dt.datetime = NOW) -> dict:
        self.events.append(kind)
        return {"gate_kind": kind, "gate_sha256": digest(kind),
                "gate_captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}

    def receipt(self, name: str) -> str:
        self.events.append(name)
        return digest(name)


def authorization() -> dict:
    return {
        "operation_id": OPERATION, "operation_nonce": digest("operation-nonce"),
        "authorization_commit": "a" * 40, "authorization_sha256": digest("authorization"),
        "authorization_history_sha256": digest("authorization-history"),
        "broker_sha256": digest("broker"), "policy_sha256": digest("policy"),
        "rollback_policy_sha256": digest("rollback-policy"), "integrated_commit": "b" * 40,
        "node": "03", "direction": "resize", "plan_sha256": digest("plan"),
        "plan_semantic_sha256": digest("semantic"), "state_lineage_sha256": digest("lineage"),
        "state_serial_before": 12, "start_by": "2026-08-21T12:30:00Z",
        "complete_by": "2026-08-21T16:30:00Z", "resource_expiry_utc": "2026-08-27T21:00:00Z",
        "minimum_recovery_margin_seconds": 86400,
    }


def verifier_receipt(value: dict) -> dict:
    return {
        "schema_version": 1, "status": "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT",
        "phase": 6, "authorization_mode": "TRANSACTION", "operation_id": value["operation_id"],
        "authorization_commit": value["authorization_commit"],
        "authorization_sha256": value["authorization_sha256"],
        "authorization_history_sha256": value["authorization_history_sha256"],
        "requires_reverification_before_use": True, "raw_values_recorded": False,
    }


def measured(value: dict) -> dict:
    return {key: value[key] for key in (
        "authorization_sha256", "broker_sha256", "policy_sha256", "rollback_policy_sha256",
    )}


def boundary(journal: dict, now: dt.datetime = NOW) -> dict:
    return {key: journal[key] for key in (
        "authorization_sha256", "authorization_history_sha256", "verifier_receipt_sha256",
        "broker_sha256", "policy_sha256", "rollback_policy_sha256",
    )} | {"measured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


class BrokerFixture:
    def __init__(self) -> None:
        self.authorization = authorization()
        self.lease = FakeLease()
        self.nonces = Nonces()
        self.journal = MODEL.start_spec_journal(
            policy=POLICY, rollback_policy=ROLLBACK_POLICY, authorization=self.authorization,
            verification_receipt=verifier_receipt(self.authorization), measured_hashes=measured(self.authorization),
            lease=self.lease, now=NOW, nonce_source=self.nonces,
        )
        self.session = MODEL.BrokerModelSession(
            policy=POLICY, journal=self.journal, lease=self.lease, nonce_source=self.nonces,
        )
        self.fake = FakeTranscriptAdapter()

    def go(self, event: dict, now: dt.datetime = NOW) -> dict:
        current = self.session.journal
        return self.session.transition(expected_generation=current["generation"],
                                       expected_nonce=current["cas_nonce"], boundary=boundary(current, now),
                                       event=event, now=now)

    def prepare(self) -> None:
        self.go({"event": "BEGIN_PREPARE", **self.fake.gate("pre_prepare")})
        self.go({"event": "PREPARE_SUCCEEDED", "prepare_receipt_sha256": self.fake.receipt("prepare")})

    def apply(self) -> None:
        self.go({"event": "BEGIN_APPLY", **self.fake.gate("pre_apply_two_survivor")})
        self.go({
            "event": "APPLY_SUCCEEDED", "phase2_receipt_sha256": self.fake.receipt("phase2"),
            "state_backup_sha256": self.fake.receipt("state-backup"),
            "pre_apply_backup_sha256": self.fake.receipt("pre-apply-backup"),
            "post_apply_backup_sha256": self.fake.receipt("post-apply-backup"),
            "state_lineage_sha256": self.authorization["state_lineage_sha256"],
            "state_serial_before": 12, "state_serial_after": 13,
        })

    def begin_recovery(self) -> None:
        self.go({
            "event": "BEGIN_RECOVERY", **self.fake.gate("pre_recovery_two_survivor"),
            "inventory_sha256": self.fake.receipt("inventory"),
            "known_hosts_sha256": self.fake.receipt("known-hosts"),
            "applied_state_receipt_sha256": self.session.journal["apply_receipt_sha256"],
        })

    def recovery_milestones(self) -> None:
        for milestone in MODEL.RECOVERY_MILESTONES[1:]:
            self.go({"event": "RECOVERY_MILESTONE", "milestone": milestone,
                     "receipt_sha256": self.fake.receipt(f"recovery-{milestone}")})


class TransactionBrokerSpecTests(unittest.TestCase):
    def test_policy_and_rollback_contracts_are_exactly_inert(self) -> None:
        MODEL.validate_policy(POLICY)
        MODEL.validate_rollback_policy(ROLLBACK_POLICY)
        self.assertIs(POLICY["execution_enabled"], False)
        self.assertIs(POLICY["production_adapter_present"], False)
        self.assertIs(POLICY["public_execution_route_present"], False)
        self.assertIs(POLICY["protected_state_boundary"]["public_phase2_apply_allowed"], False)
        self.assertIs(ROLLBACK_POLICY["execution_enabled"], False)
        self.assertEqual(ROLLBACK_POLICY["maximum_concurrent_replacements"], 1)

    def test_direct_entrypoint_unconditionally_refuses(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        self.assertIn("no execution route exists", result.stderr)
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "run_container", "adapter.phase2_apply(", "kubectl", "ansible-playbook",
                          "terraform apply", "urllib", "requests"):
            self.assertNotIn(forbidden, source)

    def test_full_fake_transcript_reaches_completed_under_one_lease(self) -> None:
        fixture = BrokerFixture(); fixture.prepare(); fixture.apply(); fixture.begin_recovery()
        fixture.recovery_milestones()
        fixture.go({"event": "RECOVERY_SUCCEEDED", "recovery_receipt_sha256": digest("recovered"),
                    "exact_effects_verified": True})
        fixture.go({"event": "BEGIN_POSTFLIGHT", **fixture.fake.gate("postflight")})
        completed = fixture.go({"event": "POSTFLIGHT_SUCCEEDED",
                                "postflight_sha256": digest("postflight"),
                                "zero_drift": True, "capacity_verified": True})
        self.assertEqual(completed["state"], "COMPLETED")
        self.assertEqual(completed["generation"], len(completed["history"]))
        self.assertEqual(completed["lease_id"], fixture.lease.lease_id)
        self.assertEqual(len({entry["cas_nonce"] for entry in completed["history"]}), len(completed["history"]))

    def test_start_requires_direct_verifier_candidate_history_and_measured_hashes(self) -> None:
        value = authorization(); lease = FakeLease(); nonces = Nonces()
        receipt = verifier_receipt(value); receipt["authorization_history_sha256"] = digest("tamper")
        with self.assertRaises(MODEL.BrokerRefused):
            MODEL.start_spec_journal(policy=POLICY, rollback_policy=ROLLBACK_POLICY, authorization=value, verification_receipt=receipt,
                                     measured_hashes=measured(value), lease=lease, now=NOW,
                                     nonce_source=nonces)
        receipt = verifier_receipt(value); hashes = measured(value); hashes["broker_sha256"] = digest("tamper")
        with self.assertRaises(MODEL.BrokerRefused):
            MODEL.start_spec_journal(policy=POLICY, rollback_policy=ROLLBACK_POLICY, authorization=value, verification_receipt=receipt,
                                     measured_hashes=hashes, lease=lease, now=NOW, nonce_source=nonces)

    def test_every_transition_rechecks_hashes_and_gate_freshness(self) -> None:
        fixture = BrokerFixture(); current = fixture.session.journal
        bad = boundary(current); bad["broker_sha256"] = digest("tamper")
        event = {"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")}
        with self.assertRaises(MODEL.BrokerRefused):
            fixture.session.transition(expected_generation=current["generation"],
                                       expected_nonce=current["cas_nonce"], boundary=bad, event=event, now=NOW)
        stale = NOW - dt.timedelta(seconds=301)
        event = {"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare", stale)}
        with self.assertRaises(MODEL.BrokerRefused): fixture.go(event)
        self.assertEqual(fixture.session.journal["state"], "AUTHORIZED")

    def test_generation_nonce_and_continuous_lease_are_not_replayable(self) -> None:
        fixture = BrokerFixture(); current = fixture.session.journal
        event = {"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")}
        with self.assertRaises(MODEL.BrokerRefused):
            fixture.session.transition(expected_generation=0, expected_nonce=current["cas_nonce"],
                                       boundary=boundary(current), event=event, now=NOW)
        fixture.lease.release_and_reacquire()
        with self.assertRaisesRegex(MODEL.BrokerRefused, "continuous"):
            fixture.go(event)

    def test_crash_adoption_rotates_lease_and_cas_before_resume(self) -> None:
        fixture = BrokerFixture()
        fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
        old = fixture.session.journal
        replacement = FakeLease(digest("lease-2")); replacement.epoch = 1
        adopted = MODEL.adopt_spec_journal(
            policy=POLICY, journal=old, lease=replacement, expected_generation=old["generation"],
            expected_nonce=old["cas_nonce"], boundary=boundary(old), now=NOW,
            nonce_source=fixture.nonces,
        )
        self.assertEqual(adopted["lease_id"], replacement.lease_id)
        self.assertEqual(adopted["history"][-1]["event"], "ADOPT_LEASE")
        resumed = MODEL.BrokerModelSession(policy=POLICY, journal=adopted, lease=replacement,
                                           nonce_source=fixture.nonces)
        retried = resumed.transition(
            expected_generation=adopted["generation"], expected_nonce=adopted["cas_nonce"],
            boundary=boundary(adopted), event={"event": "ADOPT_PREPARE_NOT_STARTED",
                                               "probe_sha256": digest("prepare-probe")}, now=NOW)
        self.assertEqual(retried["state"], "AUTHORIZED")

    def test_apply_adoption_not_started_allows_exact_retry_only(self) -> None:
        fixture = BrokerFixture(); fixture.prepare()
        fixture.go({"event": "BEGIN_APPLY", **fixture.fake.gate("pre_apply_two_survivor")})
        event = {"event": "ADOPT_APPLY", "outcome": "NOT_STARTED", "probe_sha256": digest("probe"),
                 "state_backup_sha256": digest("backup"), "exact_target_state": False,
                 "zero_drift": False, "state_lineage_sha256": fixture.authorization["state_lineage_sha256"],
                 "state_serial_after": None}
        result = fixture.go(event)
        self.assertEqual(result["state"], "PREPARED")
        with self.assertRaises(MODEL.BrokerRefused): fixture.go(event)

    def test_apply_adoption_complete_requires_target_zero_drift_backup_and_advanced_serial(self) -> None:
        fixture = BrokerFixture(); fixture.prepare()
        fixture.go({"event": "BEGIN_APPLY", **fixture.fake.gate("pre_apply_two_survivor")})
        event = {"event": "ADOPT_APPLY", "outcome": "COMPLETE", "probe_sha256": digest("probe"),
                 "state_backup_sha256": digest("backup"), "exact_target_state": True,
                 "pre_apply_backup_sha256": digest("adopt-pre-backup"),
                 "post_apply_backup_sha256": digest("adopt-post-backup"),
                 "zero_drift": True, "state_lineage_sha256": fixture.authorization["state_lineage_sha256"],
                 "state_serial_after": 13}
        bad = copy.deepcopy(event); bad["zero_drift"] = False
        with self.assertRaises(MODEL.BrokerRefused): fixture.go(bad)
        self.assertEqual(fixture.go(event)["state"], "APPLIED")

    def test_apply_partial_or_unknown_requires_exact_probe_and_stops_manual(self) -> None:
        for outcome in ("PARTIAL", "UNKNOWN"):
            with self.subTest(outcome=outcome):
                fixture = BrokerFixture(); fixture.prepare()
                fixture.go({"event": "BEGIN_APPLY", **fixture.fake.gate("pre_apply_two_survivor")})
                event = {"event": "ADOPT_APPLY", "outcome": outcome, "probe_sha256": digest(f"probe-{outcome}"),
                         "state_backup_sha256": digest("backup"), "exact_target_state": False,
                         "zero_drift": False, "state_lineage_sha256": fixture.authorization["state_lineage_sha256"],
                         "state_serial_after": None,
                         "current_state_receipt_sha256": digest(f"current-{outcome}"),
                         "current_state_lineage_sha256": fixture.authorization["state_lineage_sha256"],
                         "current_state_serial": 12}
                missing = copy.deepcopy(event); del missing["current_state_receipt_sha256"]
                with self.assertRaises(MODEL.BrokerRefused): fixture.go(missing)
                required = fixture.go(event)
                self.assertEqual(required["state"], "FAILED_SAFE")
                self.assertIs(required["manual_intervention_required"], True)

    def test_forged_completion_and_skipped_replay_are_rejected(self) -> None:
        fixture = BrokerFixture()
        forged = copy.deepcopy(fixture.session.journal)
        forged["state"] = "COMPLETED"
        forged["history"][-1]["to_state"] = "COMPLETED"
        forged["history"][-1]["projection_sha256"] = MODEL._projection(forged)
        forged["history"][-1] = MODEL._seal_entry(forged["history"][-1])
        with self.assertRaisesRegex(MODEL.BrokerRefused, "noncanonical"):
            MODEL.validate_journal(forged)
        skipped = copy.deepcopy(fixture.session.journal)
        skipped["state"] = "APPLIED"
        skipped["state_serial_after"] = 13
        skipped["apply_receipt_sha256"] = digest("forged-apply")
        skipped["state_backup_sha256"] = digest("forged-backup")
        skipped["history"][-1]["event"] = "APPLY_SUCCEEDED"
        skipped["history"][-1]["to_state"] = "APPLIED"
        skipped["history"][-1]["projection_sha256"] = MODEL._projection(skipped)
        skipped["history"][-1] = MODEL._seal_entry(skipped["history"][-1])
        with self.assertRaisesRegex(MODEL.BrokerRefused, "noncanonical"):
            MODEL.validate_journal(skipped)

    def test_partial_prepare_requires_unprepare_or_retains_manual_stop(self) -> None:
        fixture = BrokerFixture(); fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
        event = {"event": "ADOPT_PREPARE_PARTIAL", "probe_sha256": digest("prepare-probe"),
                 "prepare_milestone": "DRAINED", "unprepare_receipt_sha256": digest("unprepare"),
                 "unprepare_complete": False}
        stopped = fixture.go(event)
        self.assertEqual(stopped["state"], "FAILED_SAFE")
        self.assertIs(stopped["manual_intervention_required"], True)
        fixture = BrokerFixture(); fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare")})
        event["unprepare_complete"] = True
        restored = fixture.go(event)
        self.assertEqual(restored["state"], "AUTHORIZED")
        self.assertEqual(restored["history"][-1]["event"], "UNPREPARE_SUCCEEDED")

    def test_provider_revert_binds_fresh_plan_current_state_and_separate_backups(self) -> None:
        fixture = BrokerFixture(); fixture.prepare(); fixture.apply()
        current = fixture.session.journal
        begin = {"event": "BEGIN_ROLLBACK", **fixture.fake.gate("rollback_two_survivor"),
                 "inventory_sha256": digest("rollback-inventory"),
                 "known_hosts_sha256": digest("rollback-known-hosts"),
                 "state_backup_sha256": current["state_backup_sha256"],
                 "applied_state_receipt_sha256": current["apply_receipt_sha256"],
                 "rollback_plan_sha256": digest("rollback-plan-bytes"),
                 "rollback_plan_semantic_sha256": digest("rollback-plan-semantics"),
                 "current_state_receipt_sha256": digest("rollback-current-state"),
                 "current_state_lineage_sha256": current["state_lineage_sha256"],
                 "current_state_serial": current["state_serial_after"],
                 "pre_rollback_backup_sha256": digest("pre-rollback-backup")}
        bad = copy.deepcopy(begin); bad["current_state_serial"] += 1
        with self.assertRaises(MODEL.BrokerRefused): fixture.go(bad)
        fixture.go(begin)
        for milestone in MODEL.ROLLBACK_MILESTONES[2:]:
            fixture.go({"event": "ROLLBACK_MILESTONE", "milestone": milestone,
                        "receipt_sha256": digest(f"rollback-{milestone}")})
        result = fixture.go({"event": "ROLLBACK_SUCCEEDED",
                             "rollback_receipt_sha256": digest("rollback-complete"),
                             "post_rollback_backup_sha256": digest("post-rollback-backup"),
                             "exact_effects_verified": True})
        self.assertEqual(result["state"], "ROLLED_BACK")

    def test_recovery_milestones_are_ordered_and_unsafe_path_rolls_back(self) -> None:
        fixture = BrokerFixture(); fixture.prepare(); fixture.apply(); fixture.begin_recovery()
        with self.assertRaises(MODEL.BrokerRefused):
            fixture.go({"event": "RECOVERY_MILESTONE", "milestone": "HOST_TRUST_BOUND",
                        "receipt_sha256": digest("out-of-order")})
        required = fixture.go({"event": "FAIL_RECOVERY_UNSAFE",
                               "failure_receipt_sha256": digest("recovery-unsafe")})
        self.assertEqual(required["state"], "ROLLBACK_REQUIRED")

    def test_start_complete_and_expiry_deadlines_fail_closed(self) -> None:
        value = authorization(); value["start_by"] = "2026-08-21T12:00:00Z"
        with self.assertRaises(MODEL.BrokerRefused):
            MODEL.start_spec_journal(policy=POLICY, rollback_policy=ROLLBACK_POLICY, authorization=value,
                                     verification_receipt=verifier_receipt(value), measured_hashes=measured(value),
                                     lease=FakeLease(), now=NOW, nonce_source=Nonces())
        fixture = BrokerFixture(); after = dt.datetime(2026, 8, 21, 16, 30, tzinfo=dt.timezone.utc)
        result = fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare", after)}, now=after)
        self.assertEqual(result["state"], "FAILED_SAFE")
        self.assertEqual(result["history"][-1]["event"], "DEADLINE_EXPIRED")
        fixture = BrokerFixture()
        expiry = dt.datetime(2026, 8, 27, 21, 0, tzinfo=dt.timezone.utc)
        result = fixture.go({"event": "BEGIN_PREPARE", **fixture.fake.gate("pre_prepare", expiry)}, now=expiry)
        self.assertEqual(result["history"][-1]["event"], "RESOURCE_EXPIRED")

    def test_schemas_track_exact_model_and_remain_closed(self) -> None:
        journal_schema = json.loads((ROOT / "schemas/phase6-transaction-journal-v2.schema.json").read_text())
        policy_schema = json.loads((ROOT / "schemas/phase6-transaction-broker-policy.schema.json").read_text())
        rollback_schema = json.loads((ROOT / "schemas/phase6-transaction-rollback-policy.schema.json").read_text())
        self.assertEqual(set(journal_schema["required"]), MODEL.JOURNAL_KEYS)
        self.assertEqual(set(policy_schema["required"]), MODEL.POLICY_KEYS)
        self.assertEqual(set(rollback_schema["required"]), MODEL.ROLLBACK_POLICY_KEYS)
        self.assertIs(journal_schema["additionalProperties"], False)
        self.assertIs(policy_schema["additionalProperties"], False)
        self.assertIs(rollback_schema["additionalProperties"], False)
        jsonschema.validate(POLICY, policy_schema)
        jsonschema.validate(ROLLBACK_POLICY, rollback_schema)
        jsonschema.validate(BrokerFixture().journal, journal_schema)


if __name__ == "__main__":
    unittest.main()
