#!/usr/bin/env python3
"""Pure, dormant state model for a future inseparable Phase 6 transaction broker.

This module contains no command, network, filesystem, Kubernetes, Ansible, or
Terraform execution.  Its direct entrypoint always refuses.  It exists so the
lease/CAS/journal/adoption contract can be behaviorally reviewed before any
production adapter or mutation route is introduced.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import sys
from typing import Any, Callable, Protocol


DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
STATES = {
    "AUTHORIZED", "PREPARING", "PREPARED", "APPLYING", "APPLIED", "RECOVERING",
    "RECOVERED", "POSTFLIGHT", "COMPLETED", "ROLLBACK_REQUIRED", "ROLLING_BACK",
    "ROLLED_BACK", "FAILED_SAFE",
}
RECOVERY_MILESTONES = [
    "NONE", "INVENTORY_BOUND", "HOST_TRUST_BOUND", "JOINED_EXISTING_CLUSTER",
    "ACCESS_HARDENED", "DATA_PLANE_CONVERGED",
]
ROLLBACK_MILESTONES = [
    "NONE", "ROLLBACK_ADMITTED", "PROVIDER_REVERTED", "ORIGINAL_NODE_RECOVERED",
    "ZERO_DRIFT_VERIFIED",
]
POLICY_KEYS = {
    "schema_version", "phase", "status", "execution_enabled", "production_adapter_present",
    "public_execution_route_present", "authorization_mode",
    "authorization_receipt_requires_synchronous_reverification", "authorization_boundary", "lease_scope",
    "journal_schema_version", "journal_persistence", "operation_nonce_used_once",
    "maximum_start_window_seconds", "gate_freshness_seconds", "protected_state_boundary",
    "apply_adoption_outcomes", "recovery_milestones", "rollback_milestones", "terminal_states",
    "raw_values_recorded",
}
ROLLBACK_POLICY_KEYS = {
    "schema_version", "phase", "status", "execution_enabled", "automatic_rollback_failure_classes",
    "requires_two_survivor_gate", "requires_refreshed_inventory", "requires_refreshed_known_hosts",
    "requires_applied_state_receipt", "requires_verified_state_backup",
    "requires_zero_drift_after_rollback", "rollback_order", "maximum_concurrent_replacements",
    "rollback_must_finish_before_resource_expiry", "unsafe_or_unknown_terminal_state",
    "raw_values_recorded",
}
JOURNAL_KEYS = {
    "schema_version", "phase", "operation_id", "operation_nonce", "authorization_commit",
    "authorization_sha256", "authorization_history_sha256", "verifier_receipt_sha256", "broker_sha256", "policy_sha256",
    "rollback_policy_sha256", "integrated_commit", "node", "direction", "plan_sha256",
    "plan_semantic_sha256", "state_lineage_sha256", "state_serial_before", "state_serial_after",
    "generation", "cas_nonce", "lease_id", "state", "recovery_milestone",
    "rollback_milestone", "prepare_receipt_sha256", "apply_receipt_sha256",
    "state_backup_sha256", "recovery_receipt_sha256", "postflight_sha256",
    "rollback_receipt_sha256", "latest_gate_sha256", "failure_class", "rollback_required",
    "start_by", "complete_by", "resource_expiry_utc", "minimum_recovery_margin_seconds",
    "started_at", "updated_at", "history", "raw_values_recorded",
}
HISTORY_KEYS = {"generation", "from_state", "to_state", "event", "receipt_sha256", "cas_nonce", "captured_at"}


class BrokerRefused(ValueError):
    pass


def refuse(message: str) -> None:
    raise BrokerRefused(message)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True).encode("utf-8")).hexdigest()


def exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        refuse(f"{label} schema differs")
    return value


def timestamp(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        refuse(f"{label} must be exact UTC seconds")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        refuse(f"{label} is invalid")


def utc(now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None:
        refuse("broker clock is not timezone-aware")
    return now.astimezone(dt.timezone.utc)


def utc_text(now: dt.datetime) -> str:
    value = utc(now)
    if value.microsecond:
        refuse("broker clock must use exact UTC seconds")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_policy(policy: dict[str, Any]) -> None:
    exact_keys(policy, POLICY_KEYS, "transaction broker policy")
    fixed = {
        "schema_version": 1, "phase": 6, "status": "DORMANT_TRANSACTION_BROKER_SPEC",
        "execution_enabled": False, "production_adapter_present": False,
        "public_execution_route_present": False, "authorization_mode": "TRANSACTION",
        "authorization_receipt_requires_synchronous_reverification": True,
        "lease_scope": "FULL_TRANSACTION_AND_ADOPTION", "journal_schema_version": 2,
        "journal_persistence": "ATOMIC_CAS_BEFORE_NEXT_EFFECT", "operation_nonce_used_once": True,
        "maximum_start_window_seconds": 3600,
        "apply_adoption_outcomes": ["NOT_STARTED", "COMPLETE", "PARTIAL", "UNKNOWN"],
        "recovery_milestones": RECOVERY_MILESTONES,
        "rollback_milestones": ROLLBACK_MILESTONES,
        "terminal_states": ["COMPLETED", "ROLLED_BACK", "FAILED_SAFE"],
        "raw_values_recorded": False,
    }
    if any(policy.get(key) != value for key, value in fixed.items()):
        refuse("transaction broker policy is not the exact dormant reviewed policy")
    authorization_boundary = exact_keys(policy["authorization_boundary"], {
        "verifier_path", "candidate_history_scanner_required", "direct_verifier_before_start_required",
        "verifier_receipt_cache_allowed", "authorization_hash_recheck_before_each_effect",
        "broker_hash_recheck_before_each_effect", "policy_hash_recheck_before_each_effect",
        "rollback_policy_hash_recheck_before_each_effect",
    }, "authorization boundary policy")
    if authorization_boundary != {
        "verifier_path": "scripts/phase6/verify-github-authorization.py",
        "candidate_history_scanner_required": True, "direct_verifier_before_start_required": True,
        "verifier_receipt_cache_allowed": False, "authorization_hash_recheck_before_each_effect": True,
        "broker_hash_recheck_before_each_effect": True, "policy_hash_recheck_before_each_effect": True,
        "rollback_policy_hash_recheck_before_each_effect": True,
    }:
        refuse("authorization verifier/hash boundary differs")
    freshness = exact_keys(policy["gate_freshness_seconds"], {
        "pre_prepare", "pre_apply_two_survivor", "pre_recovery_two_survivor",
        "postflight", "rollback_two_survivor",
    }, "gate freshness policy")
    maximums = {"pre_prepare": 300, "pre_apply_two_survivor": 60,
                "pre_recovery_two_survivor": 120, "postflight": 300,
                "rollback_two_survivor": 60}
    if any(type(freshness[key]) is not int or not 0 < freshness[key] <= limit
           for key, limit in maximums.items()):
        refuse("gate freshness policy exceeds its reviewed maximum")
    boundary = exact_keys(policy["protected_state_boundary"], {
        "public_phase2_apply_allowed", "child_transaction_required", "state_sealed_before_and_after",
        "plan_staged_and_semantically_verified_before_state_open", "pre_and_post_backup_required",
        "lineage_unchanged_and_serial_advanced", "raw_provider_output_allowed",
    }, "protected state policy")
    if boundary != {
        "public_phase2_apply_allowed": False, "child_transaction_required": True,
        "state_sealed_before_and_after": True,
        "plan_staged_and_semantically_verified_before_state_open": True,
        "pre_and_post_backup_required": True, "lineage_unchanged_and_serial_advanced": True,
        "raw_provider_output_allowed": False,
    }:
        refuse("protected Phase2 child-transaction policy differs")


def validate_rollback_policy(policy: dict[str, Any]) -> None:
    exact_keys(policy, ROLLBACK_POLICY_KEYS, "transaction rollback policy")
    if policy != {
        "schema_version": 1, "phase": 6, "status": "DORMANT_TRANSACTION_ROLLBACK_SPEC",
        "execution_enabled": False,
        "automatic_rollback_failure_classes": [
            "APPLY_PARTIAL", "APPLY_UNKNOWN", "RECOVERY_UNSAFE", "POSTFLIGHT_UNSAFE",
        ],
        "requires_two_survivor_gate": True, "requires_refreshed_inventory": True,
        "requires_refreshed_known_hosts": True, "requires_applied_state_receipt": True,
        "requires_verified_state_backup": True, "requires_zero_drift_after_rollback": True,
        "rollback_order": "REVERSE_COMPLETED_RESIZE_PREFIX", "maximum_concurrent_replacements": 1,
        "rollback_must_finish_before_resource_expiry": True,
        "unsafe_or_unknown_terminal_state": "FAILED_SAFE", "raw_values_recorded": False,
    }:
        refuse("transaction rollback policy differs from the exact dormant reviewed policy")


class LeaseView(Protocol):
    operation_id: str
    lease_id: str
    epoch: int
    held: bool


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        refuse(f"{label} digest differs")
    return value


def _commit(value: object, label: str) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        refuse(f"{label} commit differs")
    return value


def validate_journal(journal: dict[str, Any]) -> None:
    exact_keys(journal, JOURNAL_KEYS, "transaction journal v2")
    if journal["schema_version"] != 2 or journal["phase"] != 6 or journal["state"] not in STATES:
        refuse("transaction journal identity or state differs")
    for key in ("operation_id", "operation_nonce", "authorization_sha256", "authorization_history_sha256",
                "verifier_receipt_sha256", "broker_sha256", "policy_sha256", "rollback_policy_sha256", "plan_sha256",
                "plan_semantic_sha256", "state_lineage_sha256", "cas_nonce", "lease_id"):
        _digest(journal[key], f"journal.{key}")
    for key in ("authorization_commit", "integrated_commit"):
        _commit(journal[key], f"journal.{key}")
    if journal["node"] not in {"01", "02", "03"} or journal["direction"] not in {"resize", "rollback"}:
        refuse("transaction journal target differs")
    if type(journal["state_serial_before"]) is not int or journal["state_serial_before"] < 0:
        refuse("transaction journal source serial differs")
    after = journal["state_serial_after"]
    if after is not None and (type(after) is not int or after <= journal["state_serial_before"]):
        refuse("transaction journal applied serial differs")
    if type(journal["generation"]) is not int or journal["generation"] < 1:
        refuse("transaction journal generation differs")
    if journal["recovery_milestone"] not in RECOVERY_MILESTONES or journal["rollback_milestone"] not in ROLLBACK_MILESTONES:
        refuse("transaction journal milestone differs")
    nullable = ("prepare_receipt_sha256", "apply_receipt_sha256", "state_backup_sha256",
                "recovery_receipt_sha256", "postflight_sha256", "rollback_receipt_sha256",
                "latest_gate_sha256")
    for key in nullable:
        if journal[key] is not None:
            _digest(journal[key], f"journal.{key}")
    if journal["failure_class"] not in {None, "APPLY_PARTIAL", "APPLY_UNKNOWN", "RECOVERY_UNSAFE",
                                         "POSTFLIGHT_UNSAFE", "ROLLBACK_UNSAFE", "POLICY_REFUSAL"}:
        refuse("transaction journal failure class differs")
    if type(journal["rollback_required"]) is not bool or journal["raw_values_recorded"] is not False:
        refuse("transaction journal safety flags differ")
    started = timestamp(journal["started_at"], "journal.started_at")
    updated = timestamp(journal["updated_at"], "journal.updated_at")
    start_by = timestamp(journal["start_by"], "journal.start_by")
    complete_by = timestamp(journal["complete_by"], "journal.complete_by")
    expiry = timestamp(journal["resource_expiry_utc"], "journal.resource_expiry_utc")
    margin = journal["minimum_recovery_margin_seconds"]
    if (margin != 86400 or not started < start_by < complete_by
            or not complete_by + dt.timedelta(seconds=margin) < expiry):
        refuse("transaction journal deadline/recovery-expiry boundary differs")
    if updated < started:
        refuse("transaction journal time moved backwards")
    history = journal["history"]
    if not isinstance(history, list) or len(history) != journal["generation"]:
        refuse("transaction journal history/generation differs")
    nonces: set[str] = set()
    prior_time: dt.datetime | None = None
    prior_state: str | None = None
    for index, entry in enumerate(history, 1):
        exact_keys(entry, HISTORY_KEYS, "transaction journal history entry")
        if entry["generation"] != index or entry["from_state"] != prior_state or entry["to_state"] not in STATES:
            refuse("transaction journal history chain differs")
        _digest(entry["cas_nonce"], "history.cas_nonce")
        if entry["cas_nonce"] in nonces:
            refuse("transaction journal reused a CAS nonce")
        nonces.add(entry["cas_nonce"])
        if entry["receipt_sha256"] is not None:
            _digest(entry["receipt_sha256"], "history.receipt_sha256")
        captured = timestamp(entry["captured_at"], "history.captured_at")
        if prior_time is not None and captured < prior_time:
            refuse("transaction journal history time moved backwards")
        prior_time, prior_state = captured, entry["to_state"]
    if prior_state != journal["state"] or history[-1]["cas_nonce"] != journal["cas_nonce"]:
        refuse("transaction journal head differs from immutable history")
    if journal["state"] in {"APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT", "COMPLETED"} and (
            journal["apply_receipt_sha256"] is None or journal["state_backup_sha256"] is None or after is None):
        refuse("post-apply journal lacks the protected apply/backup receipt")
    if journal["state"] in {"RECOVERED", "POSTFLIGHT", "COMPLETED"} and journal["recovery_receipt_sha256"] is None:
        refuse("recovered journal lacks its exact-effect receipt")
    if journal["state"] == "COMPLETED" and journal["postflight_sha256"] is None:
        refuse("completed journal lacks postflight evidence")
    if journal["state"] == "ROLLED_BACK" and journal["rollback_receipt_sha256"] is None:
        refuse("rolled-back journal lacks rollback evidence")


def _gate(event: dict[str, Any], policy: dict[str, Any], kind: str, now: dt.datetime) -> str:
    if event.get("gate_kind") != kind:
        refuse(f"{kind} gate kind differs")
    digest = _digest(event.get("gate_sha256"), f"{kind} gate")
    captured = timestamp(event.get("gate_captured_at"), f"{kind}.captured_at")
    age = (utc(now) - captured).total_seconds()
    if age < -30 or age > policy["gate_freshness_seconds"][kind]:
        refuse(f"{kind} gate is stale or future-dated")
    return digest


def start_spec_journal(*, policy: dict[str, Any], rollback_policy: dict[str, Any], authorization: dict[str, Any],
                       verification_receipt: dict[str, Any], measured_hashes: dict[str, Any], lease: LeaseView,
                       now: dt.datetime, nonce_source: Callable[[], str]) -> dict[str, Any]:
    """Create an in-memory model journal; it cannot authorize an external effect."""
    validate_policy(policy)
    validate_rollback_policy(rollback_policy)
    if not lease.held or lease.operation_id != authorization.get("operation_id"):
        refuse("the full-transaction lease is not held for this operation")
    if not DIGEST.fullmatch(lease.lease_id):
        refuse("transaction lease identity differs")
    if (verification_receipt.get("status") != "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT"
            or verification_receipt.get("authorization_commit") != authorization.get("authorization_commit")
            or verification_receipt.get("authorization_sha256") != authorization.get("authorization_sha256")
            or verification_receipt.get("authorization_history_sha256") != authorization.get("authorization_history_sha256")
            or verification_receipt.get("operation_id") != authorization.get("operation_id")
            or verification_receipt.get("requires_reverification_before_use") is not True
            or verification_receipt.get("raw_values_recorded") is not False):
        refuse("spec start lacks a synchronous verifier transcript")
    exact_keys(measured_hashes, {"authorization_sha256", "broker_sha256", "policy_sha256",
                                 "rollback_policy_sha256"}, "measured broker boundary hashes")
    exact_keys(authorization, {
        "operation_id", "operation_nonce", "authorization_commit", "authorization_sha256",
        "authorization_history_sha256", "broker_sha256", "policy_sha256", "rollback_policy_sha256",
        "integrated_commit", "node", "direction", "plan_sha256", "plan_semantic_sha256",
        "state_lineage_sha256", "state_serial_before", "start_by", "complete_by",
        "resource_expiry_utc", "minimum_recovery_margin_seconds",
    }, "spec authorization projection")
    for key in ("operation_id", "operation_nonce", "authorization_sha256", "authorization_history_sha256",
                "broker_sha256", "policy_sha256", "rollback_policy_sha256", "plan_sha256",
                "plan_semantic_sha256", "state_lineage_sha256"):
        _digest(authorization[key], f"authorization.{key}")
    _commit(authorization["authorization_commit"], "authorization.authorization_commit")
    _commit(authorization["integrated_commit"], "authorization.integrated_commit")
    if authorization["node"] not in {"01", "02", "03"} or authorization["direction"] not in {"resize", "rollback"}:
        refuse("authorization target differs")
    if type(authorization["state_serial_before"]) is not int or authorization["state_serial_before"] < 0:
        refuse("authorization state serial differs")
    if any(measured_hashes[key] != authorization[key] for key in measured_hashes):
        refuse("measured authorization/broker/policy hash differs from the hosted artifact")
    start_by = timestamp(authorization["start_by"], "authorization.start_by")
    complete_by = timestamp(authorization["complete_by"], "authorization.complete_by")
    expiry = timestamp(authorization["resource_expiry_utc"], "authorization.resource_expiry_utc")
    margin = authorization["minimum_recovery_margin_seconds"]
    if (margin != 86400 or not utc(now) < start_by < complete_by
            or not complete_by + dt.timedelta(seconds=margin) < expiry):
        refuse("transaction may not start after the authorized start-by time")
    nonce = nonce_source()
    _digest(nonce, "initial CAS nonce")
    if nonce in {authorization["operation_nonce"], authorization["operation_id"]}:
        refuse("initial CAS nonce is not independent")
    captured = utc_text(now)
    journal = {
        "schema_version": 2, "phase": 6, "operation_id": authorization["operation_id"],
        "operation_nonce": authorization["operation_nonce"],
        "authorization_commit": authorization["authorization_commit"],
        "authorization_sha256": authorization["authorization_sha256"],
        "authorization_history_sha256": authorization["authorization_history_sha256"],
        "verifier_receipt_sha256": canonical_digest(verification_receipt),
        "broker_sha256": authorization["broker_sha256"], "policy_sha256": authorization["policy_sha256"],
        "rollback_policy_sha256": authorization["rollback_policy_sha256"],
        "integrated_commit": authorization["integrated_commit"], "node": authorization["node"],
        "direction": authorization["direction"], "plan_sha256": authorization["plan_sha256"],
        "plan_semantic_sha256": authorization["plan_semantic_sha256"],
        "state_lineage_sha256": authorization["state_lineage_sha256"],
        "state_serial_before": authorization["state_serial_before"], "state_serial_after": None,
        "generation": 1, "cas_nonce": nonce, "lease_id": lease.lease_id, "state": "AUTHORIZED",
        "recovery_milestone": "NONE", "rollback_milestone": "NONE",
        "prepare_receipt_sha256": None, "apply_receipt_sha256": None, "state_backup_sha256": None,
        "recovery_receipt_sha256": None, "postflight_sha256": None,
        "rollback_receipt_sha256": None, "latest_gate_sha256": None, "failure_class": None,
        "rollback_required": False, "start_by": authorization["start_by"],
        "complete_by": authorization["complete_by"], "resource_expiry_utc": authorization["resource_expiry_utc"],
        "minimum_recovery_margin_seconds": margin, "started_at": captured, "updated_at": captured,
        "history": [{"generation": 1, "from_state": None, "to_state": "AUTHORIZED",
                     "event": "START_SPEC", "receipt_sha256": authorization["authorization_sha256"],
                     "cas_nonce": nonce, "captured_at": captured}],
        "raw_values_recorded": False,
    }
    validate_journal(journal)
    return journal


def adopt_spec_journal(*, policy: dict[str, Any], journal: dict[str, Any], lease: LeaseView,
                       expected_generation: int, expected_nonce: str, boundary: dict[str, Any],
                       now: dt.datetime, nonce_source: Callable[[], str]) -> dict[str, Any]:
    """Model crash adoption under a newly acquired canonical lease; still no external effect."""
    validate_policy(policy)
    validate_journal(journal)
    if journal["state"] in {"COMPLETED", "ROLLED_BACK", "FAILED_SAFE"}:
        refuse("terminal transaction journal cannot be adopted")
    if (not lease.held or lease.operation_id != journal["operation_id"]
            or not DIGEST.fullmatch(lease.lease_id) or lease.lease_id == journal["lease_id"]):
        refuse("crash adoption requires a newly held canonical operation lease")
    if expected_generation != journal["generation"] or expected_nonce != journal["cas_nonce"]:
        refuse("crash adoption journal generation/nonce differs")
    exact_keys(boundary, {"authorization_sha256", "authorization_history_sha256",
                          "verifier_receipt_sha256", "broker_sha256", "policy_sha256",
                          "rollback_policy_sha256", "measured_at"}, "adoption hash boundary")
    for key in ("authorization_sha256", "authorization_history_sha256", "verifier_receipt_sha256",
                "broker_sha256", "policy_sha256", "rollback_policy_sha256"):
        if boundary.get(key) != journal[key] or not DIGEST.fullmatch(boundary[key]):
            refuse("adoption authorization/broker/policy hash changed")
    current = utc(now)
    age = (current - timestamp(boundary["measured_at"], "adoption.measured_at")).total_seconds()
    if age < -30 or age > 30 or current >= timestamp(journal["resource_expiry_utc"], "journal.resource_expiry_utc"):
        refuse("adoption boundary is stale, future-dated, or beyond resource expiry")
    nonce = nonce_source()
    _digest(nonce, "adoption CAS nonce")
    if nonce in {entry["cas_nonce"] for entry in journal["history"]} | {
            journal["operation_id"], journal["operation_nonce"]}:
        refuse("adoption CAS nonce was already used")
    candidate = copy.deepcopy(journal)
    candidate["lease_id"] = lease.lease_id
    candidate["generation"] += 1
    candidate["cas_nonce"] = nonce
    candidate["updated_at"] = utc_text(now)
    candidate["history"].append({
        "generation": candidate["generation"], "from_state": candidate["state"],
        "to_state": candidate["state"], "event": "ADOPT_LEASE", "receipt_sha256": canonical_digest(boundary),
        "cas_nonce": nonce, "captured_at": candidate["updated_at"],
    })
    validate_journal(candidate)
    return candidate


class BrokerModelSession:
    """Lease-bound pure reducer. It never invokes an adapter or persists a file."""

    def __init__(self, *, policy: dict[str, Any], journal: dict[str, Any], lease: LeaseView,
                 nonce_source: Callable[[], str]) -> None:
        validate_policy(policy)
        validate_journal(journal)
        if not lease.held or lease.lease_id != journal["lease_id"] or lease.operation_id != journal["operation_id"]:
            refuse("journal is not bound to the held full-transaction lease")
        self.policy = copy.deepcopy(policy)
        self.journal = copy.deepcopy(journal)
        self.lease = lease
        self.lease_epoch = lease.epoch
        self.nonce_source = nonce_source

    def _assert_lease(self) -> None:
        if (not self.lease.held or self.lease.epoch != self.lease_epoch
                or self.lease.lease_id != self.journal["lease_id"]
                or self.lease.operation_id != self.journal["operation_id"]):
            refuse("continuous full-transaction lease was released or replaced")

    def _assert_boundary(self, boundary: dict[str, Any], now: dt.datetime) -> None:
        exact_keys(boundary, {"authorization_sha256", "authorization_history_sha256",
                              "verifier_receipt_sha256", "broker_sha256", "policy_sha256",
                              "rollback_policy_sha256", "measured_at"}, "effect hash boundary")
        for key in ("authorization_sha256", "authorization_history_sha256", "verifier_receipt_sha256",
                    "broker_sha256", "policy_sha256", "rollback_policy_sha256"):
            _digest(boundary[key], f"effect.{key}")
            if boundary[key] != self.journal[key]:
                refuse("mutation-boundary authorization/broker/policy hash changed")
        age = (utc(now) - timestamp(boundary["measured_at"], "effect.measured_at")).total_seconds()
        if age < -30 or age > 30:
            refuse("mutation-boundary hash measurement is stale or future-dated")

    def _advance(self, *, expected_generation: int, expected_nonce: str, event_name: str,
                 to_state: str, now: dt.datetime, receipt: str | None = None,
                 updates: dict[str, Any] | None = None) -> dict[str, Any]:
        self._assert_lease()
        validate_journal(self.journal)
        current_time = utc(now)
        expiry = timestamp(self.journal["resource_expiry_utc"], "journal.resource_expiry_utc")
        complete_by = timestamp(self.journal["complete_by"], "journal.complete_by")
        if current_time >= expiry:
            refuse("transaction or rollback crossed the approved resource expiry")
        if current_time >= complete_by and not (
                event_name.startswith("ROLLBACK_") or event_name.startswith("ADOPT_")
                or event_name == "BEGIN_ROLLBACK" or event_name.startswith("FAIL_")):
            refuse("forward transaction crossed complete_by; only adoption/rollback remains")
        if expected_generation != self.journal["generation"] or expected_nonce != self.journal["cas_nonce"]:
            refuse("transaction journal compare-and-swap generation/nonce differs")
        nonce = self.nonce_source()
        _digest(nonce, "next CAS nonce")
        if nonce in {entry["cas_nonce"] for entry in self.journal["history"]} | {
                self.journal["operation_nonce"], self.journal["operation_id"]}:
            refuse("transaction journal next CAS nonce was already used")
        if to_state not in STATES:
            refuse("transaction journal target state differs")
        candidate = copy.deepcopy(self.journal)
        previous = candidate["state"]
        if updates:
            candidate.update(updates)
        candidate["state"] = to_state
        candidate["generation"] += 1
        candidate["cas_nonce"] = nonce
        candidate["updated_at"] = utc_text(now)
        candidate["history"].append({
            "generation": candidate["generation"], "from_state": previous, "to_state": to_state,
            "event": event_name, "receipt_sha256": receipt, "cas_nonce": nonce,
            "captured_at": candidate["updated_at"],
        })
        validate_journal(candidate)
        self.journal = candidate
        return copy.deepcopy(candidate)

    def transition(self, *, expected_generation: int, expected_nonce: str,
                   boundary: dict[str, Any], event: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
        if not isinstance(event, dict):
            refuse("transaction event schema differs")
        self._assert_boundary(boundary, now)
        name = event.get("event")
        state = self.journal["state"]
        common = {"event"}

        if name == "BEGIN_PREPARE" and state == "AUTHORIZED":
            exact_keys(event, common | {"gate_kind", "gate_sha256", "gate_captured_at"}, "BEGIN_PREPARE")
            gate = _gate(event, self.policy, "pre_prepare", now)
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="PREPARING", now=now, receipt=gate,
                                 updates={"latest_gate_sha256": gate})
        if name in {"PREPARE_SUCCEEDED", "ADOPT_PREPARE_COMPLETE"} and state == "PREPARING":
            exact_keys(event, common | {"prepare_receipt_sha256"}, name)
            receipt = _digest(event["prepare_receipt_sha256"], "prepare receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="PREPARED", now=now, receipt=receipt,
                                 updates={"prepare_receipt_sha256": receipt})
        if name == "ADOPT_PREPARE_NOT_STARTED" and state == "PREPARING":
            exact_keys(event, common | {"probe_sha256"}, name)
            receipt = _digest(event["probe_sha256"], "prepare probe")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="AUTHORIZED", now=now, receipt=receipt)
        if name == "BEGIN_APPLY" and state == "PREPARED":
            exact_keys(event, common | {"gate_kind", "gate_sha256", "gate_captured_at"}, name)
            gate = _gate(event, self.policy, "pre_apply_two_survivor", now)
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="APPLYING", now=now, receipt=gate,
                                 updates={"latest_gate_sha256": gate})
        if name == "APPLY_SUCCEEDED" and state == "APPLYING":
            keys = common | {"phase2_receipt_sha256", "state_backup_sha256", "state_lineage_sha256",
                             "state_serial_before", "state_serial_after"}
            exact_keys(event, keys, name)
            receipt = _digest(event["phase2_receipt_sha256"], "protected Phase2 receipt")
            backup = _digest(event["state_backup_sha256"], "protected state backup")
            after = event["state_serial_after"]
            if (event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]
                    or event["state_serial_before"] != self.journal["state_serial_before"]
                    or type(after) is not int or after <= self.journal["state_serial_before"]):
                refuse("protected Phase2 receipt lineage/serial differs")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="APPLIED", now=now, receipt=receipt,
                                 updates={"apply_receipt_sha256": receipt, "state_backup_sha256": backup,
                                          "state_serial_after": after})
        if name == "ADOPT_APPLY" and state == "APPLYING":
            keys = common | {"outcome", "probe_sha256", "state_backup_sha256", "exact_target_state",
                             "zero_drift", "state_lineage_sha256", "state_serial_after"}
            exact_keys(event, keys, name)
            probe = _digest(event["probe_sha256"], "apply adoption probe")
            outcome = event["outcome"]
            if outcome == "NOT_STARTED":
                if any((event["exact_target_state"], event["zero_drift"], event["state_serial_after"] is not None)):
                    refuse("NOT_STARTED adoption contains applied-state claims")
                _digest(event["state_backup_sha256"], "adoption state backup")
                if event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]:
                    refuse("NOT_STARTED adoption lineage differs")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name="ADOPT_APPLY_NOT_STARTED", to_state="PREPARED", now=now,
                                     receipt=probe)
            if outcome == "COMPLETE":
                backup = _digest(event["state_backup_sha256"], "adoption state backup")
                after = event["state_serial_after"]
                if (event["exact_target_state"] is not True or event["zero_drift"] is not True
                        or event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]
                        or type(after) is not int or after <= self.journal["state_serial_before"]):
                    refuse("COMPLETE adoption lacks exact target, zero drift, backup, or state advancement")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name="ADOPT_APPLY_COMPLETE", to_state="APPLIED", now=now,
                                     receipt=probe, updates={"apply_receipt_sha256": probe,
                                     "state_backup_sha256": backup, "state_serial_after": after})
            if outcome in {"PARTIAL", "UNKNOWN"}:
                backup = _digest(event["state_backup_sha256"], "adoption state backup")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name=f"ADOPT_APPLY_{outcome}", to_state="ROLLBACK_REQUIRED", now=now,
                                     receipt=probe, updates={"failure_class": f"APPLY_{outcome}",
                                                             "state_backup_sha256": backup,
                                                             "rollback_required": True})
            refuse("apply adoption outcome differs")
        if name == "BEGIN_RECOVERY" and state == "APPLIED":
            keys = common | {"gate_kind", "gate_sha256", "gate_captured_at", "inventory_sha256",
                             "known_hosts_sha256", "applied_state_receipt_sha256"}
            exact_keys(event, keys, name)
            gate = _gate(event, self.policy, "pre_recovery_two_survivor", now)
            for key in ("inventory_sha256", "known_hosts_sha256", "applied_state_receipt_sha256"):
                _digest(event[key], f"recovery {key}")
            if event["applied_state_receipt_sha256"] != self.journal["apply_receipt_sha256"]:
                refuse("recovery admission is not bound to the applied-state receipt")
            receipt = canonical_digest({key: event[key] for key in sorted(keys - common)})
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="RECOVERING", now=now, receipt=receipt,
                                 updates={"latest_gate_sha256": gate})
        if name == "RECOVERY_MILESTONE" and state == "RECOVERING":
            exact_keys(event, common | {"milestone", "receipt_sha256"}, name)
            current = RECOVERY_MILESTONES.index(self.journal["recovery_milestone"])
            if current + 1 >= len(RECOVERY_MILESTONES) or event["milestone"] != RECOVERY_MILESTONES[current + 1]:
                refuse("recovery milestone is not the next idempotent exact-effect boundary")
            receipt = _digest(event["receipt_sha256"], "recovery milestone receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=f"RECOVERY_{event['milestone']}", to_state="RECOVERING", now=now,
                                 receipt=receipt, updates={"recovery_milestone": event["milestone"]})
        if name in {"RECOVERY_SUCCEEDED", "ADOPT_RECOVERY_COMPLETE"} and state == "RECOVERING":
            exact_keys(event, common | {"recovery_receipt_sha256", "exact_effects_verified"}, name)
            if self.journal["recovery_milestone"] != RECOVERY_MILESTONES[-1] or event["exact_effects_verified"] is not True:
                refuse("recovery completion lacks every exact-effect milestone")
            receipt = _digest(event["recovery_receipt_sha256"], "recovery receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="RECOVERED", now=now, receipt=receipt,
                                 updates={"recovery_receipt_sha256": receipt})
        if name == "BEGIN_POSTFLIGHT" and state == "RECOVERED":
            exact_keys(event, common | {"gate_kind", "gate_sha256", "gate_captured_at"}, name)
            gate = _gate(event, self.policy, "postflight", now)
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="POSTFLIGHT", now=now, receipt=gate,
                                 updates={"latest_gate_sha256": gate})
        if name in {"POSTFLIGHT_SUCCEEDED", "ADOPT_POSTFLIGHT_COMPLETE"} and state == "POSTFLIGHT":
            exact_keys(event, common | {"postflight_sha256", "zero_drift", "capacity_verified"}, name)
            if event["zero_drift"] is not True or event["capacity_verified"] is not True:
                refuse("postflight completion lacks zero-drift or measured-capacity evidence")
            receipt = _digest(event["postflight_sha256"], "postflight receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="COMPLETED", now=now, receipt=receipt,
                                 updates={"postflight_sha256": receipt, "rollback_required": False})
        if name == "FAIL_RECOVERY_UNSAFE" and state == "RECOVERING":
            exact_keys(event, common | {"failure_receipt_sha256"}, name)
            receipt = _digest(event["failure_receipt_sha256"], "unsafe recovery receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLBACK_REQUIRED", now=now, receipt=receipt,
                                 updates={"failure_class": "RECOVERY_UNSAFE", "rollback_required": True})
        if name == "FAIL_POSTFLIGHT_UNSAFE" and state == "POSTFLIGHT":
            exact_keys(event, common | {"failure_receipt_sha256"}, name)
            receipt = _digest(event["failure_receipt_sha256"], "unsafe postflight receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLBACK_REQUIRED", now=now, receipt=receipt,
                                 updates={"failure_class": "POSTFLIGHT_UNSAFE", "rollback_required": True})
        if name == "BEGIN_ROLLBACK" and state in {"APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT", "ROLLBACK_REQUIRED"}:
            keys = common | {"gate_kind", "gate_sha256", "gate_captured_at", "inventory_sha256",
                             "known_hosts_sha256", "applied_state_receipt_sha256", "state_backup_sha256"}
            exact_keys(event, keys, name)
            gate = _gate(event, self.policy, "rollback_two_survivor", now)
            for key in ("inventory_sha256", "known_hosts_sha256", "applied_state_receipt_sha256",
                        "state_backup_sha256"):
                _digest(event[key], f"rollback {key}")
            expected_applied = self.journal["apply_receipt_sha256"] or self.journal["history"][-1]["receipt_sha256"]
            if event["applied_state_receipt_sha256"] != expected_applied:
                refuse("rollback admission is not bound to the applied-state receipt")
            if event["state_backup_sha256"] != self.journal["state_backup_sha256"]:
                refuse("rollback admission is not bound to the verified state backup")
            receipt = canonical_digest({key: event[key] for key in sorted(keys - common)})
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLING_BACK", now=now, receipt=receipt,
                                 updates={"latest_gate_sha256": gate, "rollback_milestone": "ROLLBACK_ADMITTED"})
        if name == "ROLLBACK_MILESTONE" and state == "ROLLING_BACK":
            exact_keys(event, common | {"milestone", "receipt_sha256"}, name)
            current = ROLLBACK_MILESTONES.index(self.journal["rollback_milestone"])
            if current + 1 >= len(ROLLBACK_MILESTONES) or event["milestone"] != ROLLBACK_MILESTONES[current + 1]:
                refuse("rollback milestone is not the next idempotent exact-effect boundary")
            receipt = _digest(event["receipt_sha256"], "rollback milestone receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=f"ROLLBACK_{event['milestone']}", to_state="ROLLING_BACK", now=now,
                                 receipt=receipt, updates={"rollback_milestone": event["milestone"]})
        if name in {"ROLLBACK_SUCCEEDED", "ADOPT_ROLLBACK_COMPLETE"} and state == "ROLLING_BACK":
            exact_keys(event, common | {"rollback_receipt_sha256", "exact_effects_verified"}, name)
            if self.journal["rollback_milestone"] != ROLLBACK_MILESTONES[-1] or event["exact_effects_verified"] is not True:
                refuse("rollback completion lacks every exact-effect milestone")
            receipt = _digest(event["rollback_receipt_sha256"], "rollback receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLED_BACK", now=now, receipt=receipt,
                                 updates={"rollback_receipt_sha256": receipt, "rollback_required": False})
        if name == "FAIL_ROLLBACK_UNSAFE" and state == "ROLLING_BACK":
            exact_keys(event, common | {"failure_receipt_sha256"}, name)
            receipt = _digest(event["failure_receipt_sha256"], "unsafe rollback receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class": "ROLLBACK_UNSAFE", "rollback_required": False})
        refuse(f"event {name!r} is not allowed from journal state {state}")


def main() -> int:
    print("REFUSED: Phase 6 transaction broker is a dormant pure model; no execution route exists",
          file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
