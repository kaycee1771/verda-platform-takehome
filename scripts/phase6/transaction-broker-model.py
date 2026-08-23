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
    "generation", "cas_nonce", "lease_id", "lease_epoch", "state", "recovery_milestone",
    "rollback_milestone", "prepare_receipt_sha256", "apply_receipt_sha256",
    "state_backup_sha256", "recovery_receipt_sha256", "postflight_sha256",
    "rollback_receipt_sha256", "latest_gate_sha256", "failure_class", "rollback_required",
    "pre_apply_backup_sha256", "post_apply_backup_sha256", "rollback_plan_sha256",
    "rollback_plan_semantic_sha256", "rollback_current_state_receipt_sha256",
    "pre_rollback_backup_sha256", "post_rollback_backup_sha256",
    "reconciled_state_serial", "reconciled_state_backup", "reconciled_current_state_receipt_sha256",
    "start_by", "complete_by", "resource_expiry_utc", "minimum_recovery_margin_seconds",
    "started_at", "updated_at", "history", "manual_intervention_required", "raw_values_recorded",
}
HISTORY_KEYS = {"generation", "from_state", "to_state", "event", "receipt_sha256", "cas_nonce", "captured_at",
                "lease_epoch", "event_payload", "previous_entry_sha256", "projection", "projection_sha256", "entry_sha256"}
BACKUP_KEYS = {"receipt_sha256", "backup_identity_sha256", "state_lineage_sha256", "state_serial", "verified_at"}
BACKUP_FIELDS = {"state_backup_sha256", "pre_apply_backup_sha256", "post_apply_backup_sha256",
                 "pre_rollback_backup_sha256", "post_rollback_backup_sha256", "reconciled_state_backup"}
EFFECT_RECEIPT_KEYS = {"operation_id", "lease_id", "lease_epoch", "action", "observed_at",
                       "gate_kind", "gate_sha256", "gate_fresh", "exact_effect_verified",
                       "probe_outcome", "zero_drift", "capacity_verified", "state_lineage_sha256",
                       "state_serial_before", "state_serial_after", "backup_identity_refs",
                       "probe_evidence_sha256", "evidence_sha256"}


EVENT_SPEC: dict[str, dict[str, Any]] = {
        "START_SPEC": set(), "ADOPT_LEASE": {"lease_id"},
        "BEGIN_PREPARE": {"latest_gate_sha256"},
        "PREPARE_SUCCEEDED": {"prepare_receipt_sha256"},
        "ADOPT_PREPARE_COMPLETE": {"prepare_receipt_sha256"},
        "BEGIN_APPLY": {"latest_gate_sha256"},
        "APPLY_SUCCEEDED": {"apply_receipt_sha256", "state_backup_sha256", "pre_apply_backup_sha256",
                            "post_apply_backup_sha256", "state_serial_after"},
        "ADOPT_APPLY_COMPLETE": {"apply_receipt_sha256", "state_backup_sha256", "pre_apply_backup_sha256",
                                 "post_apply_backup_sha256", "state_serial_after"},
        "BEGIN_RECOVERY": {"latest_gate_sha256"},
        "RECOVERY_SUCCEEDED": {"recovery_receipt_sha256"},
        "ADOPT_RECOVERY_COMPLETE": {"recovery_receipt_sha256"},
        "ADOPT_RECOVERY_NOT_STARTED": set(),
        "ADOPT_RECOVERY_PARTIAL": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_RECOVERY_UNKNOWN": {"failure_class", "rollback_required", "manual_intervention_required"},
        "BEGIN_POSTFLIGHT": {"latest_gate_sha256"},
        "POSTFLIGHT_SUCCEEDED": {"postflight_sha256", "rollback_required"},
        "ADOPT_POSTFLIGHT_COMPLETE": {"postflight_sha256", "rollback_required"},
        "ADOPT_POSTFLIGHT_NOT_STARTED": set(),
        "ADOPT_POSTFLIGHT_PARTIAL": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_POSTFLIGHT_UNKNOWN": {"failure_class", "rollback_required", "manual_intervention_required"},
        "FAIL_RECOVERY_UNSAFE": {"failure_class", "rollback_required"},
        "FAIL_POSTFLIGHT_UNSAFE": {"failure_class", "rollback_required"},
        "BEGIN_ROLLBACK": {"latest_gate_sha256", "rollback_milestone", "rollback_plan_sha256",
                           "rollback_plan_semantic_sha256", "rollback_current_state_receipt_sha256",
                           "pre_rollback_backup_sha256"},
        "ROLLBACK_SUCCEEDED": {"rollback_receipt_sha256", "post_rollback_backup_sha256", "rollback_required"},
        "ADOPT_ROLLBACK_COMPLETE": {"rollback_receipt_sha256", "post_rollback_backup_sha256", "rollback_required"},
        "ADOPT_ROLLBACK_NOT_STARTED": {"rollback_milestone", "rollback_plan_sha256",
                                        "rollback_plan_semantic_sha256", "rollback_current_state_receipt_sha256",
                                        "pre_rollback_backup_sha256"},
        "ADOPT_ROLLBACK_PARTIAL": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_ROLLBACK_UNKNOWN": {"failure_class", "rollback_required", "manual_intervention_required"},
        "FAIL_ROLLBACK_UNSAFE": {"failure_class", "rollback_required", "manual_intervention_required"},
        "DEADLINE_EXPIRED": {"failure_class", "rollback_required", "manual_intervention_required"},
        "RESOURCE_EXPIRED": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_PREPARE_PARTIAL": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_PREPARE_UNKNOWN": {"failure_class", "rollback_required", "manual_intervention_required"},
        "PREPARE_ABORTED": {"failure_class", "rollback_required", "manual_intervention_required"},
        "ADOPT_APPLY_PARTIAL": {"failure_class", "state_backup_sha256", "rollback_required",
                                "manual_intervention_required", "reconciled_state_serial",
                                "reconciled_state_backup", "reconciled_current_state_receipt_sha256"},
        "ADOPT_APPLY_UNKNOWN": {"failure_class", "state_backup_sha256", "rollback_required",
                                "manual_intervention_required", "reconciled_state_serial",
                                "reconciled_state_backup", "reconciled_current_state_receipt_sha256"},
}

EVENT_CONSTANT_UPDATES = {
    "POSTFLIGHT_SUCCEEDED": {"rollback_required": False},
    "ADOPT_POSTFLIGHT_COMPLETE": {"rollback_required": False},
    "FAIL_RECOVERY_UNSAFE": {"failure_class": "RECOVERY_UNSAFE", "rollback_required": True},
    "FAIL_POSTFLIGHT_UNSAFE": {"failure_class": "POSTFLIGHT_UNSAFE", "rollback_required": True},
    "BEGIN_ROLLBACK": {"rollback_milestone": "ROLLBACK_ADMITTED"},
    "FAIL_ROLLBACK_UNSAFE": {"failure_class": "ROLLBACK_UNSAFE", "rollback_required": False,
                             "manual_intervention_required": True},
    "DEADLINE_EXPIRED": {"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                         "manual_intervention_required": True},
    "RESOURCE_EXPIRED": {"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                         "manual_intervention_required": True},
    "PREPARE_ABORTED": {"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                        "manual_intervention_required": True},
    "ADOPT_PREPARE_PARTIAL": {"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                              "manual_intervention_required": True},
    "ADOPT_PREPARE_UNKNOWN": {"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                              "manual_intervention_required": True},
    "ADOPT_APPLY_PARTIAL": {"failure_class": "APPLY_PARTIAL", "rollback_required": False,
                            "manual_intervention_required": True},
    "ADOPT_APPLY_UNKNOWN": {"failure_class": "APPLY_UNKNOWN", "rollback_required": False,
                            "manual_intervention_required": True},
    "ADOPT_RECOVERY_PARTIAL": {"failure_class": "RECOVERY_PARTIAL", "rollback_required": False,
                                "manual_intervention_required": True},
    "ADOPT_RECOVERY_UNKNOWN": {"failure_class": "RECOVERY_UNKNOWN", "rollback_required": False,
                                "manual_intervention_required": True},
    "ADOPT_POSTFLIGHT_PARTIAL": {"failure_class": "POSTFLIGHT_PARTIAL", "rollback_required": False,
                                  "manual_intervention_required": True},
    "ADOPT_POSTFLIGHT_UNKNOWN": {"failure_class": "POSTFLIGHT_UNKNOWN", "rollback_required": False,
                                  "manual_intervention_required": True},
    "ADOPT_ROLLBACK_PARTIAL": {"failure_class": "ROLLBACK_PARTIAL", "rollback_required": False,
                                "manual_intervention_required": True},
    "ADOPT_ROLLBACK_UNKNOWN": {"failure_class": "ROLLBACK_UNKNOWN", "rollback_required": False,
                                "manual_intervention_required": True},
    "ROLLBACK_SUCCEEDED": {"rollback_required": False},
    "ADOPT_ROLLBACK_COMPLETE": {"rollback_required": False},
}


def _event_spec(event: str, from_state: str | None, to_state: str) -> dict[str, Any]:
    if event in EVENT_SPEC:
        fields = EVENT_SPEC[event]
    elif event in {"ADOPT_PREPARE_NOT_STARTED", "UNPREPARE_SUCCEEDED", "ADOPT_APPLY_NOT_STARTED"}:
        fields = set()
    elif event.startswith("RECOVERY_") and event[9:] in RECOVERY_MILESTONES[1:]:
        fields = {"recovery_milestone"}
    elif event.startswith("ROLLBACK_") and event[9:] in ROLLBACK_MILESTONES[2:]:
        fields = {"rollback_milestone"}
    else:
        refuse(f"transaction replay has no closed event specification for {event}")
    event_tuple = (from_state, event, to_state)
    legal_dynamic = (
        event == "ADOPT_LEASE" and from_state == to_state
    ) or (
        event.startswith("RECOVERY_") and from_state == to_state == "RECOVERING"
        and event[9:] in RECOVERY_MILESTONES[1:]
    ) or (
        event.startswith("ROLLBACK_") and from_state == to_state == "ROLLING_BACK"
        and event[9:] in ROLLBACK_MILESTONES[2:]
    ) or (
        event == "BEGIN_ROLLBACK" and to_state == "ROLLING_BACK"
        and from_state in {"APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT", "ROLLBACK_REQUIRED"}
    ) or (
        event in {"DEADLINE_EXPIRED", "RESOURCE_EXPIRED"}
        and from_state not in {"COMPLETED", "ROLLED_BACK", "FAILED_SAFE"} and to_state == "FAILED_SAFE"
    )
    if event_tuple not in LEGAL_EVENTS and not legal_dynamic:
        refuse("transaction replay event edge differs from EVENT_SPEC")
    return {"fields": set(fields), "constants": EVENT_CONSTANT_UPDATES.get(event, {})}


def _allowed_event_fields(event: str, from_state: str | None, to_state: str) -> set[str]:
    return _event_spec(event, from_state, to_state)["fields"]


def _validate_event_field(key: str, value: Any, projection: dict[str, Any], payload: dict[str, Any]) -> None:
    if key in BACKUP_FIELDS:
        receipt = exact_keys(value, BACKUP_KEYS, f"event.{key}")
        for digest_key in ("receipt_sha256", "backup_identity_sha256", "state_lineage_sha256"):
            _digest(receipt[digest_key], f"event.{key}.{digest_key}")
        if receipt["state_lineage_sha256"] != projection["state_lineage_sha256"] or type(receipt["state_serial"]) is not int:
            refuse(f"event.{key} lineage/serial differs")
        expected_serial = {
            "state_backup_sha256": projection["state_serial_before"],
            "pre_apply_backup_sha256": projection["state_serial_before"],
            "post_apply_backup_sha256": payload.get("state_serial_after", projection.get("state_serial_after")),
            "pre_rollback_backup_sha256": projection.get("state_serial_after"),
            "post_rollback_backup_sha256": projection["state_serial_before"],
            "reconciled_state_backup": payload.get("reconciled_state_serial"),
        }[key]
        if receipt["state_serial"] != expected_serial:
            refuse(f"event.{key} serial relation differs")
        timestamp(receipt["verified_at"], f"event.{key}.verified_at")
    elif key.endswith("_sha256"):
        _digest(value, f"event.{key}")
    elif key in {"rollback_required", "manual_intervention_required"}:
        if type(value) is not bool:
            refuse(f"event.{key} must be boolean")
    elif key == "state_serial_after":
        if type(value) is not int or value <= projection["state_serial_before"]:
            refuse("event state serial did not advance")
    elif key == "reconciled_state_serial":
        if type(value) is not int or value < projection["state_serial_before"]:
            refuse("event reconciled state serial differs")
    elif key == "failure_class" and value not in {"APPLY_PARTIAL", "APPLY_UNKNOWN", "RECOVERY_PARTIAL",
                                                    "RECOVERY_UNKNOWN", "POSTFLIGHT_PARTIAL", "POSTFLIGHT_UNKNOWN",
                                                    "ROLLBACK_PARTIAL", "ROLLBACK_UNKNOWN", "RECOVERY_UNSAFE",
                                                    "POSTFLIGHT_UNSAFE", "ROLLBACK_UNSAFE", "POLICY_REFUSAL"}:
        refuse("event failure class differs")
    elif key == "recovery_milestone" and value not in RECOVERY_MILESTONES:
        refuse("event recovery milestone differs")
    elif key == "rollback_milestone" and value not in ROLLBACK_MILESTONES:
        refuse("event rollback milestone differs")


def _effect_receipt(*, projection: dict[str, Any], action: str, evidence: str,
                    observed_at: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    _digest(evidence, "effect evidence")
    changes = updates or {}
    backup_refs = sorted(value["backup_identity_sha256"] for key, value in changes.items()
                         if key in BACKUP_FIELDS and isinstance(value, dict))
    gate_kind_by_action = {"BEGIN_PREPARE": "pre_prepare", "BEGIN_APPLY": "pre_apply_two_survivor",
                           "BEGIN_RECOVERY": "pre_recovery_two_survivor", "BEGIN_POSTFLIGHT": "postflight",
                           "BEGIN_ROLLBACK": "rollback_two_survivor"}
    probe_outcome = ("EXPIRED" if action in {"DEADLINE_EXPIRED", "RESOURCE_EXPIRED"}
                     else "UNSAFE" if action.startswith("FAIL_") or action.endswith(("_PARTIAL", "_UNKNOWN"))
                     else "COMPLETE")
    decision = {"operation_id": projection["operation_id"], "lease_id": projection["lease_id"],
                "lease_epoch": projection["lease_epoch"], "action": action, "observed_at": observed_at,
                "gate_kind": gate_kind_by_action.get(action),
                "gate_sha256": changes.get("latest_gate_sha256"),
                "gate_fresh": action not in gate_kind_by_action or changes.get("latest_gate_sha256") is not None,
                "exact_effect_verified": True, "probe_outcome": probe_outcome,
                "zero_drift": True if action in {"POSTFLIGHT_SUCCEEDED", "ADOPT_POSTFLIGHT_COMPLETE",
                                                   "ROLLBACK_SUCCEEDED", "ADOPT_ROLLBACK_COMPLETE"} else None,
                "capacity_verified": True if action in {"POSTFLIGHT_SUCCEEDED",
                                                         "ADOPT_POSTFLIGHT_COMPLETE"} else None,
                "state_lineage_sha256": projection["state_lineage_sha256"],
                "state_serial_before": projection["state_serial_before"],
                "state_serial_after": changes.get("state_serial_after", projection.get("state_serial_after")),
                "backup_identity_refs": backup_refs, "probe_evidence_sha256": evidence}
    decision["evidence_sha256"] = canonical_digest(decision)
    return decision


def _validate_effect_receipt(receipt: object, *, projection: dict[str, Any], action: str) -> dict[str, Any]:
    value = exact_keys(receipt, EFFECT_RECEIPT_KEYS, "effect receipt")
    if (value["operation_id"] != projection["operation_id"] or value["lease_id"] != projection["lease_id"]
            or value["lease_epoch"] != projection["lease_epoch"] or value["action"] != action
            or value["state_lineage_sha256"] != projection["state_lineage_sha256"]
            or value["state_serial_before"] != projection["state_serial_before"]):
        refuse("effect receipt is not bound to the current fenced session")
    timestamp(value["observed_at"], "effect receipt observed_at")
    _digest(value["probe_evidence_sha256"], "effect probe evidence")
    if value["evidence_sha256"] != canonical_digest({key: item for key, item in value.items()
                                                      if key != "evidence_sha256"}):
        refuse("effect decision evidence hash differs")
    if value["exact_effect_verified"] is not True or type(value["gate_fresh"]) is not bool:
        refuse("effect decision is not exactly verified/fresh")
    if not isinstance(value["backup_identity_refs"], list) or value["backup_identity_refs"] != sorted(value["backup_identity_refs"]):
        refuse("effect decision backup references differ")
    return value

# This is deliberately a closed replay grammar.  Journal validation never trusts
# the materialized head merely because its last history row names the same state.
LEGAL_EVENTS = {
    (None, "START_SPEC", "AUTHORIZED"),
    ("AUTHORIZED", "BEGIN_PREPARE", "PREPARING"),
    ("PREPARING", "PREPARE_SUCCEEDED", "PREPARED"),
    ("PREPARING", "ADOPT_PREPARE_COMPLETE", "PREPARED"),
    ("PREPARING", "ADOPT_PREPARE_NOT_STARTED", "AUTHORIZED"),
    ("PREPARING", "ADOPT_PREPARE_PARTIAL", "FAILED_SAFE"),
    ("PREPARING", "ADOPT_PREPARE_UNKNOWN", "FAILED_SAFE"),
    ("PREPARING", "UNPREPARE_SUCCEEDED", "AUTHORIZED"),
    ("PREPARING", "PREPARE_ABORTED", "FAILED_SAFE"),
    ("PREPARED", "BEGIN_APPLY", "APPLYING"),
    ("APPLYING", "APPLY_SUCCEEDED", "APPLIED"),
    ("APPLYING", "ADOPT_APPLY_NOT_STARTED", "PREPARED"),
    ("APPLYING", "ADOPT_APPLY_COMPLETE", "APPLIED"),
    ("APPLYING", "ADOPT_APPLY_PARTIAL", "FAILED_SAFE"),
    ("APPLYING", "ADOPT_APPLY_UNKNOWN", "FAILED_SAFE"),
    ("APPLIED", "BEGIN_RECOVERY", "RECOVERING"),
    ("RECOVERING", "RECOVERY_SUCCEEDED", "RECOVERED"),
    ("RECOVERING", "ADOPT_RECOVERY_COMPLETE", "RECOVERED"),
    ("RECOVERING", "ADOPT_RECOVERY_NOT_STARTED", "APPLIED"),
    ("RECOVERING", "ADOPT_RECOVERY_PARTIAL", "FAILED_SAFE"),
    ("RECOVERING", "ADOPT_RECOVERY_UNKNOWN", "FAILED_SAFE"),
    ("RECOVERED", "BEGIN_POSTFLIGHT", "POSTFLIGHT"),
    ("POSTFLIGHT", "POSTFLIGHT_SUCCEEDED", "COMPLETED"),
    ("POSTFLIGHT", "ADOPT_POSTFLIGHT_COMPLETE", "COMPLETED"),
    ("POSTFLIGHT", "ADOPT_POSTFLIGHT_NOT_STARTED", "RECOVERED"),
    ("POSTFLIGHT", "ADOPT_POSTFLIGHT_PARTIAL", "FAILED_SAFE"),
    ("POSTFLIGHT", "ADOPT_POSTFLIGHT_UNKNOWN", "FAILED_SAFE"),
    ("RECOVERING", "FAIL_RECOVERY_UNSAFE", "ROLLBACK_REQUIRED"),
    ("POSTFLIGHT", "FAIL_POSTFLIGHT_UNSAFE", "ROLLBACK_REQUIRED"),
    ("ROLLING_BACK", "ROLLBACK_SUCCEEDED", "ROLLED_BACK"),
    ("ROLLING_BACK", "ADOPT_ROLLBACK_COMPLETE", "ROLLED_BACK"),
    ("ROLLING_BACK", "ADOPT_ROLLBACK_PARTIAL", "FAILED_SAFE"),
    ("ROLLING_BACK", "ADOPT_ROLLBACK_UNKNOWN", "FAILED_SAFE"),
    ("ROLLING_BACK", "FAIL_ROLLBACK_UNSAFE", "FAILED_SAFE"),
}


def _projection(journal: dict[str, Any]) -> str:
    return canonical_digest(_projection_value(journal))


def _projection_value(journal: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: value for key, value in journal.items() if key != "history"})


def _seal_entry(entry: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(entry)
    sealed["entry_sha256"] = canonical_digest({key: value for key, value in sealed.items()
                                                if key != "entry_sha256"})
    return sealed


IMMUTABLE_PROJECTION_KEYS = {
    "schema_version", "phase", "operation_id", "operation_nonce", "authorization_commit",
    "authorization_sha256", "authorization_history_sha256", "verifier_receipt_sha256",
    "broker_sha256", "policy_sha256", "rollback_policy_sha256", "integrated_commit", "node",
    "direction", "plan_sha256", "plan_semantic_sha256", "state_lineage_sha256",
    "state_serial_before", "start_by", "complete_by", "resource_expiry_utc",
    "minimum_recovery_margin_seconds", "started_at", "raw_values_recorded",
}


def _replay_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct every materialized projection from genesis, never from hashes."""
    previous: dict[str, Any] | None = None
    for index, entry in enumerate(history, 1):
        projection = entry["projection"]
        payload = entry["event_payload"]
        if not isinstance(payload, dict):
            refuse("transaction replay event payload differs")
        if index == 1:
            if entry["event"] != "START_SPEC" or set(payload) != {"receipt"}:
                refuse("transaction replay genesis is not exact START_SPEC")
            expected = copy.deepcopy(projection)
            if (expected["generation"] != 1 or expected["state"] != "AUTHORIZED"
                    or expected["lease_epoch"] != entry["lease_epoch"] or expected["lease_epoch"] < 0):
                refuse("transaction replay genesis projection differs")
            receipt = _validate_effect_receipt(payload["receipt"], projection=expected, action="START_SPEC")
            regenerated = _effect_receipt(projection=expected, action="START_SPEC",
                                          evidence=receipt["probe_evidence_sha256"],
                                          observed_at=entry["captured_at"])
            if receipt != regenerated or canonical_digest(receipt) != entry["receipt_sha256"]:
                refuse("START_SPEC receipt digest differs")
            for key in (JOURNAL_KEYS - IMMUTABLE_PROJECTION_KEYS - {"history", "generation", "cas_nonce",
                        "lease_id", "lease_epoch", "state", "updated_at", "manual_intervention_required"}):
                if key.endswith("_sha256") and expected[key] is not None:
                    refuse("START_SPEC forged effect evidence")
            if expected["recovery_milestone"] != "NONE" or expected["rollback_milestone"] != "NONE":
                refuse("START_SPEC forged milestones")
        else:
            assert previous is not None
            expected = copy.deepcopy(previous)
            for key in IMMUTABLE_PROJECTION_KEYS:
                if projection[key] != previous[key]:
                    refuse("transaction replay immutable projection changed")
            expected.update({"generation": index, "cas_nonce": entry["cas_nonce"],
                             "updated_at": entry["captured_at"], "state": entry["to_state"],
                             "lease_epoch": entry["lease_epoch"]})
            event = entry["event"]
            if event == "ADOPT_LEASE":
                if projection["lease_epoch"] <= previous["lease_epoch"]:
                    refuse("transaction replay lease fencing token did not advance")
                expected["lease_id"] = payload.get("lease_id")
            else:
                if projection["lease_epoch"] != previous["lease_epoch"] or projection["lease_id"] != previous["lease_id"]:
                    refuse("transaction replay effect changed its lease fence")
            spec = _event_spec(event, entry["from_state"], entry["to_state"])
            allowed = spec["fields"]
            if set(payload) != {"receipt"} | allowed:
                refuse("transaction replay payload schema differs")
            for key in allowed:
                _validate_event_field(key, payload[key], expected, payload)
                expected[key] = copy.deepcopy(payload[key])
            for key, constant in spec["constants"].items():
                if payload.get(key) != constant:
                    refuse("transaction replay constant update differs from EVENT_SPEC")
            if event.startswith("RECOVERY_") and event[9:] in RECOVERY_MILESTONES[1:]:
                prior = RECOVERY_MILESTONES.index(previous["recovery_milestone"])
                if prior + 1 >= len(RECOVERY_MILESTONES) or event[9:] != RECOVERY_MILESTONES[prior + 1]:
                    refuse("transaction replay skipped a recovery milestone")
            if event.startswith("ROLLBACK_") and event[9:] in ROLLBACK_MILESTONES[2:]:
                prior = ROLLBACK_MILESTONES.index(previous["rollback_milestone"])
                if prior + 1 >= len(ROLLBACK_MILESTONES) or event[9:] != ROLLBACK_MILESTONES[prior + 1]:
                    refuse("transaction replay skipped a rollback milestone")
            if event == "BEGIN_RECOVERY" and previous["recovery_milestone"] != "NONE":
                refuse("BEGIN_RECOVERY did not start from recovery milestone NONE")
            if event == "BEGIN_ROLLBACK" and previous["rollback_milestone"] != "NONE":
                refuse("BEGIN_ROLLBACK did not start from rollback milestone NONE")
            receipt = _validate_effect_receipt(payload["receipt"], projection=expected, action=event)
            regenerated = _effect_receipt(projection=expected, action=event,
                                          evidence=receipt["probe_evidence_sha256"],
                                          observed_at=entry["captured_at"],
                                          updates={key: payload[key] for key in allowed})
            if receipt != regenerated or canonical_digest(receipt) != entry["receipt_sha256"]:
                refuse("transaction replay decision receipt differs")
            if expected != projection:
                refuse("transaction replay projection differs from canonical event reduction")
        previous = copy.deepcopy(projection)
    assert previous is not None
    return previous


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
        "automatic_rollback_failure_classes": ["RECOVERY_UNSAFE", "POSTFLIGHT_UNSAFE"],
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


def _backup(value: object, label: str, *, lineage: str, serial: int, now: dt.datetime) -> dict[str, Any]:
    receipt = exact_keys(value, BACKUP_KEYS, label)
    _digest(receipt["receipt_sha256"], f"{label}.receipt")
    _digest(receipt["backup_identity_sha256"], f"{label}.identity")
    if receipt["state_lineage_sha256"] != lineage or receipt["state_serial"] != serial:
        refuse(f"{label} state lineage/serial differs")
    age = (utc(now) - timestamp(receipt["verified_at"], f"{label}.verified_at")).total_seconds()
    if age < -30 or age > 300:
        refuse(f"{label} verification is stale or future-dated")
    return copy.deepcopy(receipt)


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
    if type(journal["lease_epoch"]) is not int or journal["lease_epoch"] < 0:
        refuse("transaction journal lease fencing token differs")
    if journal["recovery_milestone"] not in RECOVERY_MILESTONES or journal["rollback_milestone"] not in ROLLBACK_MILESTONES:
        refuse("transaction journal milestone differs")
    nullable = ("prepare_receipt_sha256", "apply_receipt_sha256",
                "recovery_receipt_sha256", "postflight_sha256", "rollback_receipt_sha256",
                "latest_gate_sha256",
                "rollback_plan_sha256", "rollback_plan_semantic_sha256",
                "rollback_current_state_receipt_sha256", "reconciled_current_state_receipt_sha256")
    for key in nullable:
        if journal[key] is not None:
            _digest(journal[key], f"journal.{key}")
    for key in BACKUP_FIELDS:
        if journal[key] is not None:
            backup_receipt = exact_keys(journal[key], BACKUP_KEYS, f"journal.{key}")
            _digest(backup_receipt["receipt_sha256"], f"journal.{key}.receipt")
            _digest(backup_receipt["backup_identity_sha256"], f"journal.{key}.identity")
            if (backup_receipt["state_lineage_sha256"] != journal["state_lineage_sha256"]
                    or type(backup_receipt["state_serial"]) is not int or backup_receipt["state_serial"] < 0):
                refuse(f"journal.{key} lineage/serial differs")
            timestamp(backup_receipt["verified_at"], f"journal.{key}.verified_at")
    expected_backup_serials = {
        "state_backup_sha256": journal["state_serial_before"],
        "pre_apply_backup_sha256": journal["state_serial_before"],
        "post_apply_backup_sha256": after,
        "pre_rollback_backup_sha256": after,
        "post_rollback_backup_sha256": journal["state_serial_before"],
        "reconciled_state_backup": journal["reconciled_state_serial"],
    }
    identities: list[str] = []
    for key, expected_serial in expected_backup_serials.items():
        receipt = journal[key]
        if receipt is not None:
            if expected_serial is None or receipt["state_serial"] != expected_serial:
                refuse(f"journal.{key} serial relation differs")
            identities.append(receipt["backup_identity_sha256"])
    if len(identities) != len(set(identities)):
        refuse("transaction journal backup identities are not pairwise distinct")
    reconciled_serial = journal["reconciled_state_serial"]
    if reconciled_serial is not None and (type(reconciled_serial) is not int
                                           or reconciled_serial < journal["state_serial_before"]):
        refuse("transaction journal reconciled state serial differs")
    if journal["failure_class"] not in {None, "APPLY_PARTIAL", "APPLY_UNKNOWN", "RECOVERY_PARTIAL",
                                         "RECOVERY_UNKNOWN", "POSTFLIGHT_PARTIAL", "POSTFLIGHT_UNKNOWN",
                                         "ROLLBACK_PARTIAL", "ROLLBACK_UNKNOWN", "RECOVERY_UNSAFE",
                                         "POSTFLIGHT_UNSAFE", "ROLLBACK_UNSAFE", "POLICY_REFUSAL"}:
        refuse("transaction journal failure class differs")
    if (type(journal["rollback_required"]) is not bool
            or type(journal["manual_intervention_required"]) is not bool
            or journal["raw_values_recorded"] is not False):
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
    prior_entry: str | None = None
    for index, entry in enumerate(history, 1):
        exact_keys(entry, HISTORY_KEYS, "transaction journal history entry")
        if entry["generation"] != index or entry["from_state"] != prior_state or entry["to_state"] not in STATES:
            refuse("transaction journal history chain differs")
        event_tuple = (entry["from_state"], entry["event"], entry["to_state"])
        legal_dynamic = (
            entry["event"] == "ADOPT_LEASE" and entry["from_state"] == entry["to_state"]
        ) or (
            entry["event"].startswith("RECOVERY_") and entry["from_state"] == entry["to_state"] == "RECOVERING"
            and entry["event"][9:] in RECOVERY_MILESTONES[1:]
        ) or (
            entry["event"].startswith("ROLLBACK_") and entry["from_state"] == entry["to_state"] == "ROLLING_BACK"
            and entry["event"][9:] in ROLLBACK_MILESTONES[2:]
        ) or (
            entry["event"] == "BEGIN_ROLLBACK" and entry["to_state"] == "ROLLING_BACK"
            and entry["from_state"] in {"APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT", "ROLLBACK_REQUIRED"}
        ) or (
            entry["event"] in {"DEADLINE_EXPIRED", "RESOURCE_EXPIRED"}
            and entry["from_state"] not in {"COMPLETED", "ROLLED_BACK", "FAILED_SAFE"}
            and entry["to_state"] == "FAILED_SAFE"
        )
        if event_tuple not in LEGAL_EVENTS and not legal_dynamic:
            refuse("transaction journal contains a noncanonical event replay")
        if entry["previous_entry_sha256"] != prior_entry:
            refuse("transaction journal entry hash predecessor differs")
        if entry["entry_sha256"] != canonical_digest({key: value for key, value in entry.items()
                                                       if key != "entry_sha256"}):
            refuse("transaction journal entry hash differs")
        projection = exact_keys(entry["projection"], JOURNAL_KEYS - {"history"}, "history.projection")
        if entry["lease_epoch"] != projection["lease_epoch"]:
            refuse("transaction journal history fence differs from projection")
        if entry["projection_sha256"] != canonical_digest(projection):
            refuse("transaction journal per-entry projection hash differs")
        if (projection["generation"] != entry["generation"] or projection["state"] != entry["to_state"]
                or projection["cas_nonce"] != entry["cas_nonce"] or projection["updated_at"] != entry["captured_at"]):
            refuse("transaction journal per-entry projection differs from replayed event head")
        _digest(entry["cas_nonce"], "history.cas_nonce")
        if entry["cas_nonce"] in nonces:
            refuse("transaction journal reused a CAS nonce")
        nonces.add(entry["cas_nonce"])
        if entry["receipt_sha256"] is not None:
            _digest(entry["receipt_sha256"], "history.receipt_sha256")
        captured = timestamp(entry["captured_at"], "history.captured_at")
        if prior_time is not None and captured < prior_time:
            refuse("transaction journal history time moved backwards")
        prior_time, prior_state, prior_entry = captured, entry["to_state"], entry["entry_sha256"]
    if prior_state != journal["state"] or history[-1]["cas_nonce"] != journal["cas_nonce"]:
        refuse("transaction journal head differs from immutable history")
    if history[-1]["projection_sha256"] != _projection(journal):
        refuse("transaction journal materialized projection differs from canonical replay head")
    if history[-1]["projection"] != _projection_value(journal):
        refuse("transaction journal materialized values differ from canonical replay projection")
    if _replay_history(history) != _projection_value(journal):
        refuse("transaction journal deterministic replay differs from materialized head")
    if journal["state"] in {"APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT", "COMPLETED"} and (
            journal["apply_receipt_sha256"] is None or journal["state_backup_sha256"] is None or after is None
            or journal["pre_apply_backup_sha256"] is None or journal["post_apply_backup_sha256"] is None):
        refuse("post-apply journal lacks the protected apply/backup receipt")
    if journal["state"] in {"PREPARED", "APPLYING", "APPLIED", "RECOVERING", "RECOVERED", "POSTFLIGHT",
                             "COMPLETED", "ROLLBACK_REQUIRED", "ROLLING_BACK", "ROLLED_BACK"} and journal["prepare_receipt_sha256"] is None:
        refuse("prepared-or-later journal lacks prepare evidence")
    if journal["state"] in {"RECOVERED", "POSTFLIGHT", "COMPLETED"} and journal["recovery_receipt_sha256"] is None:
        refuse("recovered journal lacks its exact-effect receipt")
    if journal["state"] == "COMPLETED" and journal["postflight_sha256"] is None:
        refuse("completed journal lacks postflight evidence")
    if journal["state"] == "ROLLED_BACK" and journal["rollback_receipt_sha256"] is None:
        refuse("rolled-back journal lacks rollback evidence")
    if journal["state"] == "ROLLED_BACK" and (
            journal["rollback_milestone"] != "ZERO_DRIFT_VERIFIED"
            or journal["rollback_plan_sha256"] is None or journal["rollback_plan_semantic_sha256"] is None
            or journal["rollback_current_state_receipt_sha256"] is None
            or journal["pre_rollback_backup_sha256"] is None or journal["post_rollback_backup_sha256"] is None
            or journal["rollback_required"] is not False):
        refuse("rolled-back journal lacks its exact plan/current-state/backup/zero-drift matrix")
    if journal["state"] == "ROLLED_BACK":
        terminal_backups = [journal[key] for key in ("state_backup_sha256", "pre_apply_backup_sha256",
                            "post_apply_backup_sha256", "pre_rollback_backup_sha256",
                            "post_rollback_backup_sha256")]
        if any(item is None for item in terminal_backups) or len({item["backup_identity_sha256"] for item in terminal_backups}) != 5:
            refuse("rolled-back terminal backup identities are incomplete or equal")
    if journal["state"] == "FAILED_SAFE":
        if (journal["failure_class"] is None or journal["rollback_required"] is not False
                or journal["manual_intervention_required"] is not True):
            refuse("FAILED_SAFE journal lacks failure/manual/no-auto-rollback matrix")
        if journal["failure_class"] in {"APPLY_PARTIAL", "APPLY_UNKNOWN"} and journal["state_backup_sha256"] is None:
            refuse("uncertain apply FAILED_SAFE journal lacks reconciled current-state backup")
        if journal["failure_class"] in {"APPLY_PARTIAL", "APPLY_UNKNOWN"} and (
                journal["state_serial_after"] is not None or reconciled_serial is None
                or journal["reconciled_state_backup"] is None
                or journal["reconciled_current_state_receipt_sha256"] is None):
            refuse("uncertain apply FAILED_SAFE journal lacks exact reconciled serial/backup/current-state receipt")
        if journal["failure_class"] == "ROLLBACK_UNSAFE" and journal["rollback_milestone"] == "NONE":
            refuse("unsafe rollback FAILED_SAFE journal lacks rollback progress")
    if journal["state"] not in {"RECOVERING", "RECOVERED", "POSTFLIGHT", "COMPLETED",
                                 "ROLLBACK_REQUIRED", "ROLLING_BACK", "ROLLED_BACK", "FAILED_SAFE"} \
            and journal["recovery_milestone"] != "NONE":
        refuse("recovery milestone exists before recovery")
    if journal["state"] not in {"ROLLING_BACK", "ROLLED_BACK", "FAILED_SAFE"} \
            and journal["rollback_milestone"] != "NONE":
        refuse("rollback milestone exists before rollback")


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
            or (start_by - utc(now)).total_seconds() > policy["maximum_start_window_seconds"]
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
        "generation": 1, "cas_nonce": nonce, "lease_id": lease.lease_id, "lease_epoch": lease.epoch,
        "state": "AUTHORIZED",
        "recovery_milestone": "NONE", "rollback_milestone": "NONE",
        "prepare_receipt_sha256": None, "apply_receipt_sha256": None, "state_backup_sha256": None,
        "pre_apply_backup_sha256": None, "post_apply_backup_sha256": None,
        "rollback_plan_sha256": None, "rollback_plan_semantic_sha256": None,
        "rollback_current_state_receipt_sha256": None, "pre_rollback_backup_sha256": None,
        "post_rollback_backup_sha256": None,
        "reconciled_state_serial": None, "reconciled_state_backup": None,
        "reconciled_current_state_receipt_sha256": None,
        "recovery_receipt_sha256": None, "postflight_sha256": None,
        "rollback_receipt_sha256": None, "latest_gate_sha256": None, "failure_class": None,
        "rollback_required": False, "start_by": authorization["start_by"],
        "complete_by": authorization["complete_by"], "resource_expiry_utc": authorization["resource_expiry_utc"],
        "minimum_recovery_margin_seconds": margin, "started_at": captured, "updated_at": captured,
        "manual_intervention_required": False,
        "history": [],
        "raw_values_recorded": False,
    }
    start_receipt = _effect_receipt(projection=journal, action="START_SPEC",
                                    evidence=authorization["authorization_sha256"], observed_at=captured)
    journal["history"].append(_seal_entry({
        "generation": 1, "from_state": None, "to_state": "AUTHORIZED",
        "event": "START_SPEC", "receipt_sha256": canonical_digest(start_receipt),
        "cas_nonce": nonce, "captured_at": captured, "lease_epoch": lease.epoch,
        "event_payload": {"receipt": start_receipt},
        "previous_entry_sha256": None,
        "projection": _projection_value(journal), "projection_sha256": _projection(journal),
    }))
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
    if type(lease.epoch) is not int or lease.epoch <= journal["lease_epoch"]:
        refuse("crash adoption requires a strictly newer fencing token")
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
    candidate["lease_epoch"] = lease.epoch
    candidate["generation"] += 1
    candidate["cas_nonce"] = nonce
    candidate["updated_at"] = utc_text(now)
    adoption_effect_receipt = _effect_receipt(projection=candidate, action="ADOPT_LEASE",
                                              evidence=canonical_digest(boundary),
                                              observed_at=candidate["updated_at"])
    candidate["history"].append(_seal_entry({
        "generation": candidate["generation"], "from_state": candidate["state"],
        "to_state": candidate["state"], "event": "ADOPT_LEASE", "receipt_sha256": canonical_digest(adoption_effect_receipt),
        "cas_nonce": nonce, "captured_at": candidate["updated_at"],
        "lease_epoch": lease.epoch,
        "event_payload": {"lease_id": lease.lease_id, "receipt": adoption_effect_receipt},
        "previous_entry_sha256": journal["history"][-1]["entry_sha256"],
        "projection": _projection_value(candidate), "projection_sha256": _projection(candidate),
    }))
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
                 updates: dict[str, Any] | None = None, terminalize: bool = False) -> dict[str, Any]:
        self._assert_lease()
        validate_journal(self.journal)
        current_time = utc(now)
        expiry = timestamp(self.journal["resource_expiry_utc"], "journal.resource_expiry_utc")
        complete_by = timestamp(self.journal["complete_by"], "journal.complete_by")
        if current_time >= expiry and not terminalize:
            refuse("transaction or rollback crossed the approved resource expiry")
        if current_time >= complete_by and not terminalize and (
                event_name in {"BEGIN_PREPARE", "PREPARE_SUCCEEDED", "BEGIN_APPLY", "APPLY_SUCCEEDED"}):
            refuse("new forward preparation/apply work crossed complete_by")
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
        evidence = receipt or canonical_digest({"event": event_name, "generation": candidate["generation"]})
        effect_receipt = _effect_receipt(projection=candidate, action=event_name, evidence=evidence,
                                         observed_at=candidate["updated_at"], updates=updates)
        event_payload = {"receipt": effect_receipt}
        event_payload.update(copy.deepcopy(updates or {}))
        candidate["history"].append(_seal_entry({
            "generation": candidate["generation"], "from_state": previous, "to_state": to_state,
            "event": event_name, "receipt_sha256": canonical_digest(effect_receipt), "cas_nonce": nonce,
            "captured_at": candidate["updated_at"],
            "lease_epoch": self.lease_epoch,
            "event_payload": event_payload,
            "previous_entry_sha256": self.journal["history"][-1]["entry_sha256"],
            "projection": _projection_value(candidate), "projection_sha256": _projection(candidate),
        }))
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

        # Deadlines are themselves journal events.  They cannot leave a crash-
        # adopted operation stranded in a nonterminal state.
        current = utc(now)
        expiry = timestamp(self.journal["resource_expiry_utc"], "journal.resource_expiry_utc")
        complete_by = timestamp(self.journal["complete_by"], "journal.complete_by")
        if state not in {"COMPLETED", "ROLLED_BACK", "FAILED_SAFE"} and current >= expiry:
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name="RESOURCE_EXPIRED", to_state="FAILED_SAFE", now=now,
                                 receipt=canonical_digest({"deadline": self.journal["resource_expiry_utc"]}),
                                 updates={"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                                          "manual_intervention_required": True}, terminalize=True)
        if state in {"AUTHORIZED", "PREPARED"} and current >= complete_by:
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name="DEADLINE_EXPIRED", to_state="FAILED_SAFE", now=now,
                                 receipt=canonical_digest({"deadline": self.journal["complete_by"]}),
                                 updates={"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                                          "manual_intervention_required": True}, terminalize=True)

        if name == "BEGIN_PREPARE" and state == "AUTHORIZED":
            if current >= timestamp(self.journal["start_by"], "journal.start_by"):
                refuse("BEGIN_PREPARE crossed the authorized start_by boundary")
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
        if name in {"ADOPT_PREPARE_PARTIAL", "ADOPT_PREPARE_UNKNOWN"} and state == "PREPARING":
            exact_keys(event, common | {"probe_sha256", "prepare_milestone",
                                        "unprepare_receipt_sha256", "unprepare_complete"}, name)
            probe = _digest(event["probe_sha256"], "prepare adoption probe")
            unprepare = _digest(event["unprepare_receipt_sha256"], "unprepare receipt")
            if event["prepare_milestone"] not in {"ADMITTED", "DRAINED", "STOPPED", "UNKNOWN"}:
                refuse("prepare adoption milestone differs")
            receipt = canonical_digest({"probe": probe, "milestone": event["prepare_milestone"],
                                        "unprepare": unprepare})
            if event["unprepare_complete"] is True:
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name="UNPREPARE_SUCCEEDED", to_state="AUTHORIZED", now=now,
                                     receipt=receipt)
            if event["unprepare_complete"] is not False:
                refuse("prepare adoption unprepare result differs")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                                          "manual_intervention_required": True})
        if name == "PREPARE_ABORTED" and state == "PREPARING":
            exact_keys(event, common | {"failure_receipt_sha256"}, name)
            receipt = _digest(event["failure_receipt_sha256"], "prepare abort receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class": "POLICY_REFUSAL", "rollback_required": False,
                                          "manual_intervention_required": True})
        if name == "BEGIN_APPLY" and state == "PREPARED":
            exact_keys(event, common | {"gate_kind", "gate_sha256", "gate_captured_at"}, name)
            gate = _gate(event, self.policy, "pre_apply_two_survivor", now)
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="APPLYING", now=now, receipt=gate,
                                 updates={"latest_gate_sha256": gate})
        if name == "APPLY_SUCCEEDED" and state == "APPLYING":
            keys = common | {"phase2_receipt_sha256", "state_backup_sha256", "pre_apply_backup_sha256",
                             "post_apply_backup_sha256", "state_lineage_sha256",
                             "state_serial_before", "state_serial_after"}
            exact_keys(event, keys, name)
            receipt = _digest(event["phase2_receipt_sha256"], "protected Phase2 receipt")
            after = event["state_serial_after"]
            if (event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]
                    or event["state_serial_before"] != self.journal["state_serial_before"]
                    or type(after) is not int or after <= self.journal["state_serial_before"]):
                refuse("protected Phase2 receipt lineage/serial differs")
            backup = _backup(event["state_backup_sha256"], "protected state backup",
                             lineage=self.journal["state_lineage_sha256"], serial=self.journal["state_serial_before"], now=now)
            pre_backup = _backup(event["pre_apply_backup_sha256"], "pre-apply state backup",
                                 lineage=self.journal["state_lineage_sha256"], serial=self.journal["state_serial_before"], now=now)
            post_backup = _backup(event["post_apply_backup_sha256"], "post-apply state backup",
                                  lineage=self.journal["state_lineage_sha256"], serial=after, now=now)
            if len({backup["backup_identity_sha256"], pre_backup["backup_identity_sha256"],
                    post_backup["backup_identity_sha256"]}) != 3:
                refuse("apply backups are not separate immutable evidence")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="APPLIED", now=now, receipt=receipt,
                                 updates={"apply_receipt_sha256": receipt, "state_backup_sha256": backup,
                                          "pre_apply_backup_sha256": pre_backup,
                                          "post_apply_backup_sha256": post_backup,
                                          "state_serial_after": after})
        if name == "ADOPT_APPLY" and state == "APPLYING":
            keys = common | {"outcome", "probe_sha256", "state_backup_sha256", "exact_target_state",
                             "zero_drift", "state_lineage_sha256", "state_serial_after"}
            if event.get("outcome") in {"PARTIAL", "UNKNOWN"}:
                keys |= {"current_state_receipt_sha256", "current_state_lineage_sha256", "current_state_serial",
                         "reconciled_state_backup"}
            if event.get("outcome") == "COMPLETE":
                keys |= {"pre_apply_backup_sha256", "post_apply_backup_sha256"}
            exact_keys(event, keys, name)
            probe = _digest(event["probe_sha256"], "apply adoption probe")
            outcome = event["outcome"]
            if outcome == "NOT_STARTED":
                if any((event["exact_target_state"], event["zero_drift"], event["state_serial_after"] is not None)):
                    refuse("NOT_STARTED adoption contains applied-state claims")
                _backup(event["state_backup_sha256"], "adoption state backup",
                        lineage=self.journal["state_lineage_sha256"],
                        serial=self.journal["state_serial_before"], now=now)
                if event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]:
                    refuse("NOT_STARTED adoption lineage differs")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name="ADOPT_APPLY_NOT_STARTED", to_state="PREPARED", now=now,
                                     receipt=probe)
            if outcome == "COMPLETE":
                after = event["state_serial_after"]
                if (event["exact_target_state"] is not True or event["zero_drift"] is not True
                        or event["state_lineage_sha256"] != self.journal["state_lineage_sha256"]
                        or type(after) is not int or after <= self.journal["state_serial_before"]):
                    refuse("COMPLETE adoption lacks exact target, zero drift, backup, or state advancement")
                backup = _backup(event["state_backup_sha256"], "adoption state backup",
                                 lineage=self.journal["state_lineage_sha256"], serial=self.journal["state_serial_before"], now=now)
                pre_backup = _backup(event["pre_apply_backup_sha256"], "adoption pre-apply backup",
                                     lineage=self.journal["state_lineage_sha256"], serial=self.journal["state_serial_before"], now=now)
                post_backup = _backup(event["post_apply_backup_sha256"], "adoption post-apply backup",
                                      lineage=self.journal["state_lineage_sha256"], serial=after, now=now)
                if len({backup["backup_identity_sha256"], pre_backup["backup_identity_sha256"],
                        post_backup["backup_identity_sha256"]}) != 3:
                    refuse("adopted apply backups are not separate immutable evidence")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name="ADOPT_APPLY_COMPLETE", to_state="APPLIED", now=now,
                                     receipt=probe, updates={"apply_receipt_sha256": probe,
                                     "state_backup_sha256": backup, "pre_apply_backup_sha256": pre_backup,
                                     "post_apply_backup_sha256": post_backup, "state_serial_after": after})
            if outcome in {"PARTIAL", "UNKNOWN"}:
                backup = _backup(event["state_backup_sha256"], "adoption state backup",
                                 lineage=self.journal["state_lineage_sha256"],
                                 serial=self.journal["state_serial_before"], now=now)
                # Uncertain provider effects are a manual stop, never an
                # automatic revert.  A read-only exact-current-state receipt is
                # mandatory even to classify the stop safely.
                current_receipt = event.get("current_state_receipt_sha256")
                current_lineage = event.get("current_state_lineage_sha256")
                current_serial = event.get("current_state_serial")
                if (not isinstance(current_receipt, str) or not DIGEST.fullmatch(current_receipt)
                        or current_lineage != self.journal["state_lineage_sha256"]
                        or type(current_serial) is not int or current_serial < self.journal["state_serial_before"]):
                    refuse("uncertain apply lacks exact read-only current-state evidence")
                reconciled_backup = _backup(event["reconciled_state_backup"], "reconciled current-state backup",
                                            lineage=self.journal["state_lineage_sha256"],
                                            serial=current_serial, now=now)
                if reconciled_backup["backup_identity_sha256"] == backup["backup_identity_sha256"]:
                    refuse("uncertain apply original and reconciled backup identities are equal")
                return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                     event_name=f"ADOPT_APPLY_{outcome}", to_state="FAILED_SAFE", now=now,
                                     receipt=canonical_digest({"probe": probe, "current": current_receipt,
                                                               "lineage": current_lineage, "serial": current_serial}),
                                     updates={"failure_class": f"APPLY_{outcome}",
                                                             "state_backup_sha256": backup,
                                                             "reconciled_state_serial": current_serial,
                                                             "reconciled_state_backup": reconciled_backup,
                                                             "reconciled_current_state_receipt_sha256": current_receipt,
                                                             "rollback_required": False,
                                                             "manual_intervention_required": True})
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
            exact_keys(event, common | {"milestone", "receipt_sha256", "effect_probe_sha256",
                                        "exact_effect_verified"}, name)
            current = RECOVERY_MILESTONES.index(self.journal["recovery_milestone"])
            if current + 1 >= len(RECOVERY_MILESTONES) or event["milestone"] != RECOVERY_MILESTONES[current + 1]:
                refuse("recovery milestone is not the next idempotent exact-effect boundary")
            receipt = _digest(event["receipt_sha256"], "recovery milestone receipt")
            probe = _digest(event["effect_probe_sha256"], "recovery effect probe")
            if event["exact_effect_verified"] is not True:
                refuse("recovery milestone effect was not idempotently observed before CAS")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=f"RECOVERY_{event['milestone']}", to_state="RECOVERING", now=now,
                                 receipt=canonical_digest({"receipt": receipt, "probe": probe}),
                                 updates={"recovery_milestone": event["milestone"]})
        if name in {"RECOVERY_SUCCEEDED", "ADOPT_RECOVERY_COMPLETE"} and state == "RECOVERING":
            exact_keys(event, common | {"recovery_receipt_sha256", "exact_effects_verified"}, name)
            if self.journal["recovery_milestone"] != RECOVERY_MILESTONES[-1] or event["exact_effects_verified"] is not True:
                refuse("recovery completion lacks every exact-effect milestone")
            receipt = _digest(event["recovery_receipt_sha256"], "recovery receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="RECOVERED", now=now, receipt=receipt,
                                 updates={"recovery_receipt_sha256": receipt})
        if name == "ADOPT_RECOVERY_NOT_STARTED" and state == "RECOVERING":
            exact_keys(event, common | {"probe_sha256", "exact_no_effect"}, name)
            if event["exact_no_effect"] is not True or self.journal["recovery_milestone"] != "NONE":
                refuse("recovery NOT_STARTED lacks exact no-effect proof")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="APPLIED", now=now,
                                 receipt=_digest(event["probe_sha256"], "recovery no-effect probe"))
        if name in {"ADOPT_RECOVERY_PARTIAL", "ADOPT_RECOVERY_UNKNOWN"} and state == "RECOVERING":
            exact_keys(event, common | {"probe_sha256", "current_state_receipt_sha256"}, name)
            receipt=canonical_digest({"probe":_digest(event["probe_sha256"], "recovery uncertain probe"),
                                      "current":_digest(event["current_state_receipt_sha256"], "recovery current state")})
            outcome=name.rsplit("_",1)[1]
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class":f"RECOVERY_{outcome}","rollback_required":False,
                                          "manual_intervention_required":True})
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
        if name == "ADOPT_POSTFLIGHT_NOT_STARTED" and state == "POSTFLIGHT":
            exact_keys(event, common | {"probe_sha256", "exact_no_effect"}, name)
            if event["exact_no_effect"] is not True: refuse("postflight NOT_STARTED lacks exact no-effect proof")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="RECOVERED", now=now,
                                 receipt=_digest(event["probe_sha256"], "postflight no-effect probe"))
        if name in {"ADOPT_POSTFLIGHT_PARTIAL", "ADOPT_POSTFLIGHT_UNKNOWN"} and state == "POSTFLIGHT":
            exact_keys(event, common | {"probe_sha256", "current_state_receipt_sha256"}, name)
            outcome=name.rsplit("_",1)[1]
            receipt=canonical_digest({"probe":_digest(event["probe_sha256"], "postflight uncertain probe"),
                                      "current":_digest(event["current_state_receipt_sha256"], "postflight current state")})
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class":f"POSTFLIGHT_{outcome}","rollback_required":False,
                                          "manual_intervention_required":True})
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
                             "known_hosts_sha256", "applied_state_receipt_sha256", "state_backup_sha256",
                             "rollback_plan_sha256", "rollback_plan_semantic_sha256",
                             "current_state_receipt_sha256", "current_state_lineage_sha256",
                             "current_state_serial", "pre_rollback_backup_sha256"}
            exact_keys(event, keys, name)
            gate = _gate(event, self.policy, "rollback_two_survivor", now)
            for key in ("inventory_sha256", "known_hosts_sha256", "applied_state_receipt_sha256",
                        "rollback_plan_sha256", "rollback_plan_semantic_sha256",
                        "current_state_receipt_sha256"):
                _digest(event[key], f"rollback {key}")
            if (event["current_state_lineage_sha256"] != self.journal["state_lineage_sha256"]
                    or event["current_state_serial"] != self.journal["state_serial_after"]):
                refuse("rollback plan is not bound to the exact read-only current state")
            expected_applied = self.journal["apply_receipt_sha256"] or self.journal["history"][-1]["receipt_sha256"]
            if event["applied_state_receipt_sha256"] != expected_applied:
                refuse("rollback admission is not bound to the applied-state receipt")
            if event["state_backup_sha256"] != self.journal["state_backup_sha256"]:
                refuse("rollback admission is not bound to the verified state backup")
            pre_rollback = _backup(event["pre_rollback_backup_sha256"], "pre-rollback backup",
                                   lineage=self.journal["state_lineage_sha256"],
                                   serial=self.journal["state_serial_after"], now=now)
            if pre_rollback["backup_identity_sha256"] in {
                    self.journal["state_backup_sha256"]["backup_identity_sha256"],
                    self.journal["post_apply_backup_sha256"]["backup_identity_sha256"]}:
                refuse("pre-rollback backup is not distinct immutable evidence")
            receipt = canonical_digest({key: event[key] for key in sorted(keys - common)})
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLING_BACK", now=now, receipt=receipt,
                                 updates={"latest_gate_sha256": gate, "rollback_milestone": "ROLLBACK_ADMITTED",
                                          "rollback_plan_sha256": event["rollback_plan_sha256"],
                                          "rollback_plan_semantic_sha256": event["rollback_plan_semantic_sha256"],
                                          "rollback_current_state_receipt_sha256": event["current_state_receipt_sha256"],
                                          "pre_rollback_backup_sha256": pre_rollback})
        if name == "ROLLBACK_MILESTONE" and state == "ROLLING_BACK":
            exact_keys(event, common | {"milestone", "receipt_sha256", "effect_probe_sha256",
                                        "exact_effect_verified"}, name)
            current = ROLLBACK_MILESTONES.index(self.journal["rollback_milestone"])
            if current + 1 >= len(ROLLBACK_MILESTONES) or event["milestone"] != ROLLBACK_MILESTONES[current + 1]:
                refuse("rollback milestone is not the next idempotent exact-effect boundary")
            receipt = _digest(event["receipt_sha256"], "rollback milestone receipt")
            probe = _digest(event["effect_probe_sha256"], "rollback effect probe")
            if event["exact_effect_verified"] is not True:
                refuse("rollback milestone effect was not idempotently observed before CAS")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=f"ROLLBACK_{event['milestone']}", to_state="ROLLING_BACK", now=now,
                                 receipt=canonical_digest({"receipt": receipt, "probe": probe}),
                                 updates={"rollback_milestone": event["milestone"]})
        if name in {"ROLLBACK_SUCCEEDED", "ADOPT_ROLLBACK_COMPLETE"} and state == "ROLLING_BACK":
            exact_keys(event, common | {"rollback_receipt_sha256", "post_rollback_backup_sha256",
                                        "exact_effects_verified", "zero_drift"}, name)
            if (self.journal["rollback_milestone"] != ROLLBACK_MILESTONES[-1]
                    or event["exact_effects_verified"] is not True or event["zero_drift"] is not True):
                refuse("rollback completion lacks every exact-effect milestone")
            receipt = _digest(event["rollback_receipt_sha256"], "rollback receipt")
            post_backup = _backup(event["post_rollback_backup_sha256"], "post-rollback state backup",
                                  lineage=self.journal["state_lineage_sha256"],
                                  serial=self.journal["state_serial_before"], now=now)
            if post_backup["backup_identity_sha256"] in {
                    self.journal["state_backup_sha256"]["backup_identity_sha256"],
                    self.journal["pre_rollback_backup_sha256"]["backup_identity_sha256"]}:
                refuse("post-rollback backup is not separate immutable evidence")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="ROLLED_BACK", now=now, receipt=receipt,
                                 updates={"rollback_receipt_sha256": receipt,
                                          "post_rollback_backup_sha256": post_backup,
                                          "rollback_required": False})
        if name in {"ADOPT_ROLLBACK_PARTIAL", "ADOPT_ROLLBACK_UNKNOWN"} and state == "ROLLING_BACK":
            exact_keys(event, common | {"probe_sha256", "current_state_receipt_sha256"}, name)
            outcome=name.rsplit("_",1)[1]
            receipt=canonical_digest({"probe":_digest(event["probe_sha256"], "rollback uncertain probe"),
                                      "current":_digest(event["current_state_receipt_sha256"], "rollback current state")})
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class":f"ROLLBACK_{outcome}","rollback_required":False,
                                          "manual_intervention_required":True})
        if name == "FAIL_ROLLBACK_UNSAFE" and state == "ROLLING_BACK":
            exact_keys(event, common | {"failure_receipt_sha256"}, name)
            receipt = _digest(event["failure_receipt_sha256"], "unsafe rollback receipt")
            return self._advance(expected_generation=expected_generation, expected_nonce=expected_nonce,
                                 event_name=name, to_state="FAILED_SAFE", now=now, receipt=receipt,
                                 updates={"failure_class": "ROLLBACK_UNSAFE", "rollback_required": False,
                                          "manual_intervention_required": True})
        refuse(f"event {name!r} is not allowed from journal state {state}")


def main() -> int:
    print("REFUSED: Phase 6 transaction broker is a dormant pure model; no execution route exists",
          file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
