#!/usr/bin/env python3
"""Focused positive and negative tests for Phase 6 serial resize admission."""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "management-node-resize.py"
CONTRACT_PATH = ROOT / "config" / "phase6-management-resize.json"
SPEC = importlib.util.spec_from_file_location("phase6_resize", SCRIPT)
assert SPEC and SPEC.loader
RESIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESIZE)
COLLECTOR_SCRIPT = ROOT / "scripts" / "phase6" / "management-resize-collector.py"
COLLECTOR_SPEC = importlib.util.spec_from_file_location("phase6_resize_collector", COLLECTOR_SCRIPT)
assert COLLECTOR_SPEC and COLLECTOR_SPEC.loader
COLLECTOR = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(COLLECTOR)
INVENTORY_SCRIPT = ROOT / "scripts" / "phase6" / "generate-resize-inventory.py"
INVENTORY_SPEC = importlib.util.spec_from_file_location("phase6_resize_inventory", INVENTORY_SCRIPT)
assert INVENTORY_SPEC and INVENTORY_SPEC.loader
INVENTORY = importlib.util.module_from_spec(INVENTORY_SPEC)
INVENTORY_SPEC.loader.exec_module(INVENTORY)
NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)
COMMIT = "a" * 40
AUTHOR = "b" * 64
REVIEWER = "c" * 64
OWNER = "d" * 64
LINEAGE = "5" * 64
STATE_SERIAL = 10


def active_contract() -> dict:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    value["activation"] = {
        "enabled": True,
        "writes_allowed": True,
        "integrated_commit": COMMIT,
        "reason": "test-only activated copy",
    }
    value["terraform"]["target_resource_expiry_utc"] = "2026-08-27T21:00:00Z"
    return value


def plan(node: str = "03", direction: str = "resize") -> dict:
    source = "CPU.4V.16G" if direction == "resize" else "CPU.8V.32G"
    target = "CPU.8V.32G" if direction == "resize" else "CPU.4V.16G"
    source_expiry = "2026-08-24T21:00:00Z" if direction == "resize" else "2026-08-27T21:00:00Z"
    target_expiry = "2026-08-27T21:00:00Z" if direction == "resize" else "2026-08-24T21:00:00Z"

    def instance(instance_type: str, expiry: str) -> dict:
        return {
            "hostname": f"verda-mgmt-server-{node}",
            "instance_type": instance_type,
            "description": f"verda-mgmt server; owner=platform; expires={expiry}",
            "image": "ubuntu-24.04",
            "location": "FIN-03",
            "is_spot": False,
            "os_volume": {"name": f"verda-mgmt-os-{node}", "size": 80, "type": "NVMe"},
            "existing_volumes": ["sensitive-provider-volume-id"],
            "ssh_key_ids": ["sensitive-provider-key-id"],
            "startup_script_id": None,
        }

    return {
        "complete": True,
        "applyable": True,
        "errored": False,
        "resource_drift": [],
        "timestamp": NOW.isoformat(),
        "format_version": "1.2",
        "terraform_version": "1.15.8",
        "configuration": {"root_module": {"module_calls": {}}},
        "prior_state": {"format_version": "1.0", "values": {}},
        "resource_changes": [
            {
                "address": f'module.management.module.node["{node}"].verda_instance.this',
                "type": "verda_instance",
                "change": {
                    "actions": ["delete", "create"],
                    "before": instance(source, source_expiry),
                    "after": instance(target, target_expiry),
                },
            }
        ]
    }


def progress(resized: list[str] | None = None, rolled_back: list[str] | None = None, in_flight: str | None = None) -> dict:
    operation_id = "e" * 64 if in_flight else None
    return {
        "schema_version": 1,
        "integrated_commit": COMMIT,
        "completed_resize_nodes": resized or [],
        "completed_rollback_nodes": rolled_back or [],
        "generation": 1,
        "used_operation_ids": [operation_id] if operation_id else [],
        "in_flight_node": in_flight,
        "in_flight_direction": "resize" if in_flight else None,
        "in_flight_operation_id": operation_id,
        "in_flight_plan_sha256": "f" * 64 if in_flight else None,
        "in_flight_recovery_sha256": None,
        "in_flight_started_at": NOW.isoformat() if in_flight else None,
    }


class ContractTests(unittest.TestCase):
    def test_checked_in_contract_is_valid_and_inert(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        RESIZE.validate_contract(contract)
        self.assertFalse(contract["activation"]["enabled"])
        self.assertFalse(contract["activation"]["writes_allowed"])
        self.assertIsNone(contract["activation"]["integrated_commit"])

    def test_exact_shape_order_and_join_peers_are_pinned(self) -> None:
        contract = active_contract()
        self.assertEqual(contract["terraform"]["target_instance_type"], "CPU.8V.32G")
        self.assertEqual(contract["serial"]["resize_order"], ["03", "02", "01"])
        self.assertEqual(contract["serial"]["join_peers"]["01"], "02")
        RESIZE.validate_contract(contract)

    def test_shape_or_parallelism_change_is_rejected(self) -> None:
        contract = active_contract()
        contract["terraform"]["target_instance_type"] = "CPU.16V.64G"
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.validate_contract(contract)
        contract = active_contract()
        contract["serial"]["maximum_concurrent_replacements"] = 2
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.validate_contract(contract)

    def test_node02_may_be_selected_first_when_node03_is_leader(self) -> None:
        contract = active_contract()
        contract["serial"]["resize_order"] = ["02", "03", "01"]
        contract["serial"]["rollback_order"] = ["01", "03", "02"]
        RESIZE.validate_contract(contract)

    def test_disabled_activation_refuses_live_admission(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "activation is disabled"):
            RESIZE.require_activation(contract, COMMIT)


class SerialProgressTests(unittest.TestCase):
    def test_resize_is_exact_prefix_and_primary_is_last(self) -> None:
        contract = active_contract()
        self.assertEqual(RESIZE.expected_node(contract, progress(), "resize"), "03")
        self.assertEqual(RESIZE.expected_node(contract, progress(["03"]), "resize"), "02")
        self.assertEqual(RESIZE.expected_node(contract, progress(["03", "02"]), "resize"), "01")

    def test_out_of_order_or_concurrent_progress_is_rejected(self) -> None:
        contract = active_contract()
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.expected_node(contract, progress(["02"]), "resize")
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "remains in flight"):
            RESIZE.expected_node(contract, progress(in_flight="03"), "resize")

    def test_immediate_rollback_of_in_flight_node_is_allowed(self) -> None:
        self.assertEqual(RESIZE.expected_node(active_contract(), progress(in_flight="03"), "rollback"), "03")

    def test_ordered_rollback_requires_full_resize(self) -> None:
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "fully resized"):
            RESIZE.expected_node(active_contract(), progress(["03"]), "rollback")
        self.assertEqual(RESIZE.expected_node(active_contract(), progress(["03", "02", "01"]), "rollback"), "01")


class PlanTests(unittest.TestCase):
    def test_exact_single_node_resize_and_rollback_pass(self) -> None:
        resized = RESIZE.assert_plan(plan(), active_contract(), "03", "resize", NOW)
        rolled_back = RESIZE.assert_plan(plan("01", "rollback"), active_contract(), "01", "rollback", NOW)
        self.assertEqual(resized["target_instance_type"], "CPU.8V.32G")
        self.assertEqual(rolled_back["target_instance_type"], "CPU.4V.16G")

    def test_extra_change_is_rejected(self) -> None:
        candidate = plan()
        candidate["resource_changes"].append(copy.deepcopy(candidate["resource_changes"][0]))
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "exactly one"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)

    def test_wrong_node_or_shape_is_rejected(self) -> None:
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_plan(plan("02"), active_contract(), "03", "resize", NOW)
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["instance_type"] = "CPU.16V.64G"
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)

    def test_data_volume_or_ssh_key_change_is_rejected(self) -> None:
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["existing_volumes"] = ["other"]
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "data volume"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["ssh_key_ids"] = ["other"]
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "SSH key"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)

    def test_incomplete_drifted_targeted_or_stale_plan_is_rejected(self) -> None:
        defects = [
            ("complete", False),
            ("applyable", False),
            ("errored", True),
            ("resource_drift", [{"address": "redacted"}]),
            ("target_addrs", ["redacted"]),
            ("timestamp", (NOW - dt.timedelta(hours=2)).isoformat()),
            ("terraform_version", "1.15.9"),
            ("format_version", "1.1"),
        ]
        for key, value in defects:
            with self.subTest(key=key):
                candidate = plan()
                candidate[key] = value
                with self.assertRaises(RESIZE.ResizeRefused):
                    RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)

    def test_create_before_delete_and_missing_configuration_are_rejected(self) -> None:
        candidate = plan()
        candidate["resource_changes"][0]["change"]["actions"] = ["create", "delete"]
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "delete-then-create"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)
        candidate = plan()
        candidate["configuration"] = {}
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "configuration"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize", NOW)


class JournalAndLeaseTests(unittest.TestCase):
    def test_nonce_is_used_once_and_postflight_is_hash_bound(self) -> None:
        contract = active_contract()
        operation = "1" * 64
        plan_sha = "2" * 64
        recovery_sha = "3" * 64
        applied = RESIZE.transition_progress(
            progress(), contract, event="apply", direction="resize", node="03",
            operation_id=operation, plan_sha256=plan_sha, captured_at=NOW.isoformat(),
        )
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "consumed"):
            RESIZE.transition_progress(
                applied, contract, event="apply", direction="resize", node="03",
                operation_id=operation, plan_sha256=plan_sha,
            )
        recovered = RESIZE.transition_progress(
            applied, contract, event="recovery", direction="resize", node="03",
            operation_id=operation, plan_sha256=plan_sha, recovery_sha256=recovery_sha,
        )
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "stale"):
            RESIZE.transition_progress(
                recovered, contract, event="postflight", direction="resize", node="03",
                operation_id=operation, plan_sha256="4" * 64, recovery_sha256=recovery_sha,
            )
        completed = RESIZE.transition_progress(
            recovered, contract, event="postflight", direction="resize", node="03",
            operation_id=operation, plan_sha256=plan_sha, recovery_sha256=recovery_sha,
        )
        self.assertEqual(completed["completed_resize_nodes"], ["03"])
        self.assertIsNone(completed["in_flight_node"])

    def test_immediate_rollback_transition_is_reachable(self) -> None:
        contract = active_contract()
        applied = RESIZE.transition_progress(
            progress(), contract, event="apply", direction="resize", node="03",
            operation_id="1" * 64, plan_sha256="2" * 64, captured_at=NOW.isoformat(),
        )
        rollback = RESIZE.transition_progress(
            applied, contract, event="apply", direction="rollback", node="03",
            operation_id="3" * 64, plan_sha256="4" * 64, captured_at=NOW.isoformat(),
        )
        self.assertEqual(rollback["in_flight_direction"], "rollback")
        self.assertEqual(rollback["in_flight_node"], "03")
        recovered = RESIZE.transition_progress(
            rollback, contract, event="recovery", direction="rollback", node="03",
            operation_id="3" * 64, plan_sha256="4" * 64, recovery_sha256="5" * 64,
        )
        completed = RESIZE.transition_progress(
            recovered, contract, event="postflight", direction="rollback", node="03",
            operation_id="3" * 64, plan_sha256="4" * 64, recovery_sha256="5" * 64,
        )
        self.assertEqual(completed["completed_resize_nodes"], [])
        self.assertEqual(completed["completed_rollback_nodes"], [])
        self.assertEqual(RESIZE.expected_node(contract, completed, "resize"), "03")

    def test_os_exclusive_lease_rejects_a_second_holder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "phase6.lock"
            with RESIZE.ExclusiveLease(path, "1" * 64):
                with self.assertRaisesRegex(RESIZE.ResizeRefused, "OS-exclusive"):
                    with RESIZE.ExclusiveLease(path, "2" * 64):
                        self.fail("second lock unexpectedly acquired")

    def test_reviewed_worktree_must_be_exactly_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = pathlib.Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "phase6@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Phase6 Test"], cwd=repository, check=True)
            tracked = repository / "critical.txt"
            tracked.write_text("reviewed\n", encoding="utf-8")
            subprocess.run(["git", "add", "critical.txt"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repository, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True,
            ).stdout.strip()
            RESIZE.assert_clean_reviewed_worktree(repository, commit)
            tracked.write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "not exactly clean"):
                RESIZE.assert_clean_reviewed_worktree(repository, commit)


class GateTests(unittest.TestCase):
    def bundle(self, contract: dict, gate_name: str, node: str = "03") -> dict:
        return {
            "schema_version": 1,
            "phase": 6,
            "cluster": "management",
            "integrated_commit": COMMIT,
            "node": node,
            "captured_at": NOW.isoformat(),
            "checks": contract[gate_name],
        }

    def test_exact_fresh_gate_bundle_passes(self) -> None:
        contract = active_contract()
        RESIZE.assert_gate_bundle(
            self.bundle(contract, "required_preflight"), contract["required_preflight"], COMMIT, "03", contract, NOW, "preflight"
        )

    def test_stale_or_partial_gate_bundle_is_rejected(self) -> None:
        contract = active_contract()
        stale = self.bundle(contract, "required_preflight")
        stale["captured_at"] = (NOW - dt.timedelta(hours=1)).isoformat()
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_gate_bundle(stale, contract["required_preflight"], COMMIT, "03", contract, NOW, "preflight")
        partial = self.bundle(contract, "required_preflight")
        partial["checks"] = dict(partial["checks"])
        partial["checks"].pop("etcd_quorum")
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_gate_bundle(partial, contract["required_preflight"], COMMIT, "03", contract, NOW, "preflight")

    def test_cost_and_worst_two_capacity_must_meet_bound_contract(self) -> None:
        contract = active_contract()
        cost = {
            "schema_version": 1, "phase": 6, "integrated_commit": COMMIT,
            "captured_at": NOW.isoformat(), "shape": "CPU.8V.32G", "location": "FIN-03",
            "on_demand_available": True, "price_per_instance_hour_usd": 0.0558,
            "project_balance_usd": 70.45, "seven_day_envelope_usd": 66.6747,
            "raw_values_recorded": False,
        }
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "price, balance"):
            RESIZE.assert_cost_receipt(cost, contract, COMMIT, NOW)
        capacity = {
            "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "candidate_node_count": 3,
            "minimum_observed_per_node_cpu_millicores": 7000,
            "minimum_observed_per_node_memory_bytes": 30_000_000_000,
            "worst_two_allocatable_cpu_millicores": 13584,
            "worst_two_allocatable_memory_bytes": 60_000_000_000,
            "projection_sha256": "9" * 64, "raw_values_recorded": False,
        }
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "worst-two"):
            RESIZE.assert_capacity_receipt(capacity, contract, COMMIT)
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "trusted collector measurements"):
            RESIZE.assert_measured_capacity({
                "minimum_observed_per_node_cpu_millicores": 7000,
                "minimum_observed_per_node_memory_bytes": 30_000_000_000,
                "worst_two_allocatable_cpu_millicores": 13584,
                "worst_two_allocatable_memory_bytes": 60_000_000_000,
            }, contract)

    def test_lease_expiry_and_same_reviewer_are_rejected(self) -> None:
        lease = {
            "schema_version": 1,
            "phase": 6,
            "integrated_commit": COMMIT,
            "owner_digest": OWNER,
            "writes_allowed": True,
            "expires_at": (NOW - dt.timedelta(seconds=1)).isoformat(),
        }
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "expired"):
            RESIZE.assert_lease(lease, COMMIT, NOW)
        review = {
            "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "node": "03", "direction": "resize",
            "operation_id": "0" * 64, "plan_sha256": "1" * 64, "plan_semantic_sha256": "2" * 64,
            "preflight_sha256": "3" * 64, "contract_sha256": "4" * 64,
            "cost_receipt_sha256": "5" * 64, "capacity_receipt_sha256": "6" * 64,
            "collector_report_sha256": "7" * 64, "tool_lock_sha256": "8" * 64,
            "state_lineage_sha256": LINEAGE, "state_serial": STATE_SERIAL,
            "author_digest": AUTHOR, "reviewer_digest": AUTHOR, "reliability_reviewer_digest": "e" * 64,
            "security_approved": True, "capacity_approved": True, "reliability_approved": True,
        }
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "must be distinct"):
            RESIZE.assert_review(
                review, COMMIT, "03", "resize", "0" * 64, "1" * 64, "2" * 64,
                "3" * 64, "4" * 64, "5" * 64, "6" * 64, "7" * 64, "8" * 64,
                LINEAGE, STATE_SERIAL,
            )


class AdmissionTests(unittest.TestCase):
    def test_full_admission_is_hash_bound_and_identity_free(self) -> None:
        with tempfile.TemporaryDirectory() as external_name:
            external = pathlib.Path(external_name)
            contract = active_contract()
            contract_path = external / "contract.json"
            progress_path = external / "progress.json"
            preflight_path = external / "preflight.json"
            review_path = external / "review.json"
            lease_path = external / "lease.json"
            cost_path = external / "cost.json"
            capacity_path = external / "capacity.json"
            collector_path = external / "collector.json"
            plan_path = external / "node03.tfplan"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            progress_path.write_text(json.dumps(progress()), encoding="utf-8")
            preflight = {
                "schema_version": 1, "phase": 6, "cluster": "management", "integrated_commit": COMMIT,
                "node": "03", "captured_at": NOW.isoformat(), "checks": contract["required_preflight"],
            }
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            plan_path.write_bytes(b"opaque saved terraform plan")
            cost_path.write_text(json.dumps({
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT,
                "captured_at": NOW.isoformat(), "shape": "CPU.8V.32G", "location": "FIN-03",
                "on_demand_available": True, "price_per_instance_hour_usd": 0.0558,
                "project_balance_usd": 100.0, "seven_day_envelope_usd": 66.6747,
                "raw_values_recorded": False,
            }), encoding="utf-8")
            capacity_path.write_text(json.dumps({
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "candidate_node_count": 3,
                "minimum_observed_per_node_cpu_millicores": 7000,
                "minimum_observed_per_node_memory_bytes": 30_000_000_000,
                "worst_two_allocatable_cpu_millicores": 14000,
                "worst_two_allocatable_memory_bytes": 60_000_000_000,
                "projection_sha256": "9" * 64, "raw_values_recorded": False,
            }), encoding="utf-8")
            collector_path.write_text("{}", encoding="utf-8")
            semantic_sha = RESIZE.canonical_digest(RESIZE.assert_plan(plan(), contract, "03", "resize", NOW))
            tool_lock_sha = RESIZE.canonical_digest({
                "versions_lock": RESIZE.digest_file(ROOT / "versions.lock.yaml"),
                "terraform_lock": RESIZE.digest_file(
                    ROOT / "infra" / "terraform" / "environments" / "management" / ".terraform.lock.hcl"
                ),
                "controller": RESIZE.digest_file(SCRIPT),
                "collector": RESIZE.digest_file(COLLECTOR_SCRIPT),
                "prepare_playbook": RESIZE.digest_file(
                    ROOT / "infra" / "ansible" / "playbooks" / "prepare-management-node-resize.yml"
                ),
                "recovery_playbook": RESIZE.digest_file(
                    ROOT / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml"
                ),
                "prepare_helper": RESIZE.digest_file(
                    ROOT / "scripts" / "phase6" / "prepare-management-node-resize.sh"
                ),
                "remove_helper": RESIZE.digest_file(
                    ROOT / "scripts" / "phase6" / "remove-stale-management-member.sh"
                ),
                "authorization_verifier": RESIZE.digest_file(
                    ROOT / "scripts" / "phase6" / "assert-operation-authorization.py"
                ),
                "phase2_boundary": RESIZE.digest_file(ROOT / "scripts" / "infra" / "phase2.ps1"),
                "management_group_vars": RESIZE.digest_file(
                    ROOT / "infra" / "ansible" / "inventories" / "group_vars" / "management_servers.yml"
                ),
            })
            review = {
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "node": "03", "direction": "resize",
                "operation_id": "0" * 64, "plan_sha256": RESIZE.digest_file(plan_path),
                "plan_semantic_sha256": semantic_sha, "preflight_sha256": RESIZE.digest_file(preflight_path),
                "contract_sha256": RESIZE.digest_file(contract_path),
                "cost_receipt_sha256": RESIZE.digest_file(cost_path),
                "capacity_receipt_sha256": RESIZE.digest_file(capacity_path),
                "collector_report_sha256": RESIZE.digest_file(collector_path), "tool_lock_sha256": tool_lock_sha,
                "state_lineage_sha256": LINEAGE, "state_serial": STATE_SERIAL,
                "author_digest": AUTHOR, "reviewer_digest": REVIEWER,
                "reliability_reviewer_digest": "e" * 64,
                "security_approved": True, "capacity_approved": True, "reliability_approved": True,
            }
            review_path.write_text(json.dumps(review), encoding="utf-8")
            lease = {
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "owner_digest": OWNER,
                "writes_allowed": True, "expires_at": (NOW + dt.timedelta(minutes=5)).isoformat(),
            }
            lease_path.write_text(json.dumps(lease), encoding="utf-8")
            measured = {
                "minimum_observed_per_node_cpu_millicores": 7000,
                "minimum_observed_per_node_memory_bytes": 30_000_000_000,
                "worst_two_allocatable_cpu_millicores": 14000,
                "worst_two_allocatable_memory_bytes": 60_000_000_000,
            }
            with mock.patch.object(RESIZE, "assert_clean_reviewed_worktree") as clean, mock.patch.object(
                RESIZE, "assert_trusted_collector_report", return_value=measured
            ), mock.patch.object(RESIZE, "terraform_show", return_value=plan()):
                summary = RESIZE.admission(
                    contract_path=contract_path, progress_path=progress_path, saved_plan=plan_path,
                    preflight_path=preflight_path, review_path=review_path, lease_path=lease_path,
                    cost_path=cost_path, capacity_path=capacity_path, collector_path=collector_path,
                    operation_id="0" * 64, survivor="01", direction="resize", git_commit=COMMIT,
                    repository=ROOT, state_lineage_sha256=LINEAGE, state_serial=STATE_SERIAL,
                    inventory_path=collector_path, known_hosts_path=collector_path,
                    now=NOW,
                )
                clean.assert_called_once_with(ROOT, COMMIT)
            rendered = json.dumps(summary)
            self.assertEqual(summary["replacement_count"], 1)
            self.assertEqual(summary["reviewer_count"], 3)
            self.assertNotIn("sensitive-provider", rendered)
            self.assertNotIn("address", rendered)

    def test_plan_inside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as repo_name:
            repo = pathlib.Path(repo_name)
            plan_path = repo / "unsafe.tfplan"
            plan_path.write_bytes(b"plan")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "outside"):
                RESIZE.assert_outside_repository(plan_path, repo, "saved plan")


class RecoverySourceTests(unittest.TestCase):
    def test_node01_replacement_always_joins_a_surviving_peer(self) -> None:
        template = (ROOT / "infra" / "ansible" / "roles" / "rke2_server" / "templates" / "rke2-node.yaml.j2").read_text()
        self.assertIn("phase4_join_existing_cluster", template)
        self.assertIn("phase4_join_server_address", template)
        playbook = (ROOT / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml").read_text()
        self.assertIn("verda-mgmt-server-01: verda-mgmt-server-02", playbook)
        self.assertIn("phase4_join_existing_cluster: true", playbook)

    def test_recovery_converges_all_wireguard_peers_and_prunes_one_member(self) -> None:
        playbook = (ROOT / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml").read_text()
        self.assertGreaterEqual(playbook.count("hosts: management_servers"), 2)
        self.assertIn("remove-stale-management-member.sh", playbook)
        remover = (ROOT / "scripts" / "phase6" / "remove-stale-management-member.sh").read_text()
        self.assertIn("member_count", remover)
        self.assertIn("member remove", remover)
        self.assertIn("remaining", remover)
        self.assertIn("Ready", remover)
        self.assertIn("other_survivor_address", remover)
        self.assertIn("^[0-9a-f]{16}$", remover)

    def test_prepare_owns_pdb_drain_quiesce_storage_evacuation_and_rebuild(self) -> None:
        prepare = (ROOT / "infra" / "ansible" / "playbooks" / "prepare-management-node-resize.yml").read_text()
        helper = (ROOT / "scripts" / "phase6" / "prepare-management-node-resize.sh").read_text()
        recovery = (ROOT / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml").read_text()
        self.assertIn("cordon", helper)
        self.assertIn("drain", helper)
        self.assertNotIn("--force", helper)
        self.assertNotIn("--disable-eviction", helper)
        self.assertIn('"evictionRequested":true', helper)
        self.assertIn('"$target_replicas" == 0', helper)
        self.assertIn("Stop the selected RKE2 server", prepare)
        self.assertIn("state: unmounted", prepare)
        self.assertLess(prepare.index("state: stopped"), prepare.index("state: unmounted"))
        self.assertIn("--post-quiesce", prepare)
        self.assertIn("--post-recovery", recovery)
        self.assertIn('"allowScheduling":true', helper)
        self.assertIn("replacement Ready and Longhorn scheduling/rebuild restored", helper)

    def test_terraform_uses_only_the_checked_in_per_node_lifecycle_map(self) -> None:
        variables = (ROOT / "infra" / "terraform" / "environments" / "management" / "variables.tf").read_text()
        cluster = (ROOT / "infra" / "terraform" / "modules" / "verda-cluster" / "main.tf").read_text()
        management = (ROOT / "infra" / "terraform" / "environments" / "management" / "main.tf").read_text()
        self.assertEqual(management.count('instance_type       = "CPU.4V.16G"'), 3)
        self.assertEqual(management.count('resource_expiry_utc = "2026-08-24T21:00:00Z"'), 3)
        self.assertIn("each.value.instance_type", cluster)
        self.assertIn("each.value.resource_expiry_utc", cluster)
        self.assertNotIn("instance_type_overrides", variables + cluster)

    def test_controller_contains_no_target_or_replace_plan_escape_hatch(self) -> None:
        controller = SCRIPT.read_text()
        self.assertNotIn('"-target', controller)
        self.assertNotIn('"-replace', controller)

    def test_direct_helpers_refuse_before_any_cluster_command_without_controller_authorization(self) -> None:
        operation = "0" * 64
        commands = [
            ["bash", "scripts/phase6/prepare-management-node-resize.sh",
             "verda-mgmt-server-03", "--prepare", "missing", operation],
            ["bash", "scripts/phase6/remove-stale-management-member.sh",
             "verda-mgmt-server-03", "10.250.0.12", "missing", operation],
        ]
        for command in commands:
            with self.subTest(helper=pathlib.Path(command[1]).name):
                result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
                self.assertEqual(result.returncode, 64, result.stdout + result.stderr)
        for playbook_name in ("prepare-management-node-resize.yml", "recover-resized-management-node.yml"):
            plays = yaml.safe_load((ROOT / "infra" / "ansible" / "playbooks" / playbook_name).read_text())
            self.assertIn("Verify the controller-issued", plays[0]["tasks"][0]["name"])

    def test_authorization_verifier_refuses_the_checked_in_inert_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            operation = "0" * 64
            journal = external / "journal.json"
            authorization = external / "authorization.json"
            journal.write_text(json.dumps({
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT,
                "operation_id": operation, "node": "03", "direction": "resize", "state": "PREPARED",
            }), encoding="utf-8")
            authorization.write_text(json.dumps({
                "schema_version": 1, "phase": 6, "status": "CONTROLLER_OPERATION_AUTHORIZED",
                "integrated_commit": COMMIT, "operation_id": operation, "node": "03",
                "direction": "resize", "mode": "prepare",
                "contract_sha256": RESIZE.digest_file(CONTRACT_PATH),
                "journal_sha256": RESIZE.digest_file(journal),
                "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat(),
                "raw_values_recorded": False,
            }), encoding="utf-8")
            result = subprocess.run([
                "python", str(ROOT / "scripts" / "phase6" / "assert-operation-authorization.py"),
                "--authorization", str(authorization), "--contract", str(CONTRACT_PATH),
                "--journal", str(journal), "--authorization-sha256", RESIZE.digest_file(authorization),
                "--operation-id", operation, "--commit", COMMIT, "--node", "03",
                "--direction", "resize", "--mode", "prepare",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 64)
            self.assertIn("active external contract", result.stderr)

    def test_cli_exposes_only_reviewed_operation_routes(self) -> None:
        parser = RESIZE.build_parser()
        choices = next(action.choices for action in parser._actions if getattr(action, "choices", None))
        self.assertEqual(set(choices), {"validate-contract", "apply-node", "adopt-apply", "recover-node"})
        phase2 = (ROOT / "scripts" / "infra" / "phase2.ps1").read_text()
        self.assertIn("phase6-resize-apply", phase2)
        self.assertIn("Invoke-Phase6ResizeApply", phase2)


class ProtectedStateSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "scripts" / "infra" / "phase2.ps1").read_text(encoding="utf-8")

    def section(self, start: str, end: str) -> str:
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def test_phase6_has_explicit_plan_apply_state_and_output_boundaries(self) -> None:
        self.assertIn("'phase6-resize-plan'", self.source)
        self.assertIn("'phase6-resize-apply'", self.source)
        self.assertIn("'phase6-resize-state'", self.source)
        self.assertIn("'phase6-resize-no-drift'", self.source)
        self.assertIn("'phase6-resize-output'", self.source)
        self.assertIn("Invoke-Phase6ResizeApply", self.source)
        self.assertIn("Assert-OutsideRepository -Path $statePath", self.source)
        self.assertIn("Close-SealedState -Paths $paths", self.source)
        self.assertIn("$phase6ProtectedTarget -and $phase6StateOpened", self.source)

    def test_plan_is_ordinary_saved_plan_and_exit_zero_is_refused(self) -> None:
        section = self.section("function Invoke-Phase6ResizePlan", "function Invoke-Phase6ResizeOutput")
        self.assertIn("'-detailed-exitcode'", section)
        self.assertIn("-AcceptedExitCodes @(2)", section)
        self.assertNotIn("-target=", section)
        self.assertNotIn("-replace=", section)

    def test_protected_terraform_does_not_tee_raw_output(self) -> None:
        section = self.section("function Invoke-Phase6Terraform", "function Invoke-Phase6ResizePlan")
        self.assertIn("*> $logPath", section)
        self.assertNotIn("Tee-Object", section)
        self.assertIn("raw diagnostic withheld", section)
        self.assertIn("'init', '-reconfigure', '-input=false', '-lockfile=readonly'", section)
        self.assertIn('"-backend-config=path=$($Paths.StatePath)"', section)

    def test_output_is_state_bound_and_hashes_nonsecret_descriptors(self) -> None:
        section = self.section("function Invoke-Phase6ResizeOutput", "function Invoke-Inventory")
        for marker in (
            "state_lineage_sha256", "state_serial", "inventory_sha256",
            "known_hosts_sha256", "private_key_public_sha256",
        ):
            self.assertIn(marker, section)

    @unittest.skipUnless(os.name == "nt", "DPAPI/reparse behavioral boundary is Windows-only")
    def test_dot_source_cannot_expose_or_invoke_phase6_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory) / "base"
            backup = pathlib.Path(directory) / "backup"
            driver = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'fake terraform invoked' }}
try {{ . '{ROOT / 'scripts' / 'infra' / 'phase2.ps1'}' -Target phase6-resize-apply }} catch {{ $caught = $_.Exception.Message }}
$applyCommand = Get-Command Invoke-Phase6ResizeApply -ErrorAction SilentlyContinue
if ($applyCommand -or $script:terraformCalled) {{ exit 91 }}
if ([string]::IsNullOrWhiteSpace($caught)) {{ exit 92 }}
"apply-unreachable"
"""
            result = subprocess.run(
                ["pwsh", "-NoLogo", "-NoProfile", "-Command", driver],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("apply-unreachable", result.stdout)

    @unittest.skipUnless(os.name == "nt", "DPAPI/reparse behavioral boundary is Windows-only")
    def test_alias_matrix_preserves_protected_assets_without_terraform(self) -> None:
        aliases = ("state", "sealed", "key", "known_hosts", "backup")
        for alias in aliases:
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                base, backup = root / "base", root / "backup"
                base.mkdir()
                backup.mkdir()
                state = base / "terraform" / "management.tfstate"
                key = base / "ssh" / "id_ed25519"
                known_hosts = base / "ssh" / "known_hosts"
                state.parent.mkdir()
                key.parent.mkdir()
                sentinels = {
                    "state": state,
                    "sealed": pathlib.Path(f"{state}.dpapi"),
                    "key": key,
                    "known_hosts": known_hosts,
                    "backup": backup / "protected.tfstate.dpapi",
                }
                for name, path in sentinels.items():
                    path.write_text(f"sentinel-{name}", encoding="utf-8")
                candidate = sentinels[alias]
                driver = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{state}'
$env:VERDA_CLIENT_ID = 'test-only'
$env:VERDA_CLIENT_SECRET = 'test-only'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'fake terraform invoked' }}
try {{
  & '{ROOT / 'scripts' / 'infra' / 'phase2.ps1'}' -Target phase6-resize-plan `
    -SavedPlan '{candidate}' -ExpectedStateLineageSha256 ('a' * 64) -ExpectedStateSerial 1 -OperationId ('b' * 64)
  exit 81
}} catch {{
  if ($script:terraformCalled) {{ exit 82 }}
}}
"alias-refused"
"""
                result = subprocess.run(
                    ["pwsh", "-NoLogo", "-NoProfile", "-Command", driver],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("alias-refused", result.stdout)
                for name, path in sentinels.items():
                    self.assertEqual(path.read_text(encoding="utf-8"), f"sentinel-{name}")

    @unittest.skipUnless(os.name == "nt", "DPAPI/reparse behavioral boundary is Windows-only")
    def test_inventory_output_alias_matrix_preserves_assets_without_terraform(self) -> None:
        aliases = ("state", "sealed", "key", "known_hosts", "backup")
        for alias in aliases:
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                base, backup = root / "base", root / "backup"
                base.mkdir()
                backup.mkdir()
                state = base / "terraform" / "management.tfstate"
                key = base / "ssh" / "id_ed25519"
                known_hosts = base / "ssh" / "known_hosts"
                state.parent.mkdir()
                key.parent.mkdir()
                sentinels = {
                    "state": state,
                    "sealed": pathlib.Path(f"{state}.dpapi"),
                    "key": key,
                    "known_hosts": known_hosts,
                    "backup": backup / "protected.tfstate.dpapi",
                }
                for name, path in sentinels.items():
                    path.write_text(f"sentinel-{name}", encoding="utf-8")
                driver = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{state}'
$env:VERDA_CLIENT_ID = 'test-only'
$env:VERDA_CLIENT_SECRET = 'test-only'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'fake terraform invoked' }}
try {{
  & '{ROOT / 'scripts' / 'infra' / 'phase2.ps1'}' -Target phase6-resize-output `
    -InventoryOutput '{sentinels[alias]}' -KnownHosts '{known_hosts}' `
    -ExpectedStateLineageSha256 ('a' * 64) -ExpectedStateSerial 1 -OperationId ('b' * 64)
  exit 61
}} catch {{
  if ($script:terraformCalled) {{ exit 62 }}
}}
"inventory-alias-refused"
"""
                result = subprocess.run(
                    ["pwsh", "-NoLogo", "-NoProfile", "-Command", driver],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("inventory-alias-refused", result.stdout)
                for name, path in sentinels.items():
                    self.assertEqual(path.read_text(encoding="utf-8"), f"sentinel-{name}")

    @unittest.skipUnless(os.name == "nt", "Windows hard-link/reparse behavior")
    def test_existing_hardlink_and_reparse_plan_directory_are_refused(self) -> None:
        for mode in ("hardlink", "junction"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                base, backup = root / "base", root / "backup"
                state = base / "terraform" / "management.tfstate"
                state.parent.mkdir(parents=True)
                backup.mkdir()
                state.write_text("protected-state", encoding="utf-8")
                phase6 = base / "phase6"
                phase6.mkdir()
                plan_dir = phase6 / "plans"
                candidate = plan_dir / "node03.tfplan"
                if mode == "hardlink":
                    plan_dir.mkdir()
                    os.link(state, candidate)
                else:
                    result = subprocess.run(
                        ["pwsh", "-NoLogo", "-NoProfile", "-Command",
                         f"New-Item -ItemType Junction -Path '{plan_dir}' -Target '{backup}' | Out-Null"],
                        check=False, capture_output=True, text=True,
                    )
                    if result.returncode != 0:
                        self.skipTest("junction creation unavailable")
                driver = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{state}'
$env:VERDA_CLIENT_ID = 'test-only'
$env:VERDA_CLIENT_SECRET = 'test-only'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'fake terraform invoked' }}
try {{
  & '{ROOT / 'scripts' / 'infra' / 'phase2.ps1'}' -Target phase6-resize-plan `
    -SavedPlan '{candidate}' -ExpectedStateLineageSha256 ('a' * 64) -ExpectedStateSerial 1 -OperationId ('b' * 64)
  exit 51
}} catch {{ if ($script:terraformCalled) {{ exit 52 }} }}
"alias-type-refused"
"""
                result = subprocess.run(
                    ["pwsh", "-NoLogo", "-NoProfile", "-Command", driver],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("alias-type-refused", result.stdout)
                self.assertEqual(state.read_text(encoding="utf-8"), "protected-state")

    @unittest.skipUnless(os.name == "nt", "DPAPI failure sealing is Windows-only")
    def test_failure_after_open_reseals_state_and_withholds_fake_terraform_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state = base / "terraform" / "management.tfstate"
            plan_path = base / "phase6" / "plans" / "node03.tfplan"
            fake_bin = root / "fake-bin"
            marker = root / "terraform-invoked"
            state.parent.mkdir(parents=True)
            backup.mkdir()
            fake_bin.mkdir()
            state.write_text('{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}', encoding="utf-8")
            (fake_bin / "terraform.cmd").write_text(
                f"@echo off\r\necho SENSITIVE-FAKE-TERRAFORM 1>&2\r\necho invoked>\"{marker}\"\r\nexit /b 1\r\n",
                encoding="utf-8",
            )
            driver = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{state}'
$env:VERDA_CLIENT_ID = 'test-only'
$env:VERDA_CLIENT_SECRET = 'test-only'
$env:PATH = '{fake_bin};' + $env:PATH
try {{
  & '{ROOT / 'scripts' / 'infra' / 'phase2.ps1'}' -Target phase6-resize-plan `
    -SavedPlan '{plan_path}' -ExpectedStateLineageSha256 ('a' * 64) -ExpectedStateSerial 1 -OperationId ('b' * 64)
  exit 71
}} catch {{ "generic-failure" }}
"""
            result = subprocess.run(
                ["pwsh", "-NoLogo", "-NoProfile", "-Command", driver],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(state.exists())
            self.assertTrue(pathlib.Path(f"{state}.dpapi").is_file())
            self.assertTrue(marker.is_file())
            self.assertNotIn("SENSITIVE-FAKE-TERRAFORM", result.stdout + result.stderr)


class TrustedInputAndCollectorTests(unittest.TestCase):
    @staticmethod
    def canonical_inventory() -> dict:
        hosts = {}
        for index in range(1, 4):
            name = f"verda-mgmt-server-{index:02d}"
            hosts[name] = {
                "ansible_host": f"192.0.2.{index}", "ansible_user": "root", "node_name": name,
                "role": "server", "internal_ip": f"10.0.0.{index}", "wireguard_ip": f"10.250.0.1{index}",
                "data_volume_id": f"volume-{index}", "attached_device_id": f"volume-{index}",
                "data_volume_size_gib": 100,
            }
        return {"all": {"children": {"management_servers": {"hosts": hosts}}}}

    @mock.patch.object(INVENTORY.subprocess, "run")
    def test_inventory_validation_rejects_duplicate_ip_and_attachment_drift(self, run: mock.Mock) -> None:
        run.return_value.returncode = 0
        candidate = self.canonical_inventory()
        known_hosts = pathlib.Path("/protected/known_hosts")
        INVENTORY.validate_inventory(candidate, known_hosts)
        duplicate = copy.deepcopy(candidate)
        duplicate["all"]["children"]["management_servers"]["hosts"]["verda-mgmt-server-03"]["ansible_host"] = "192.0.2.1"
        with self.assertRaisesRegex(ValueError, "not unique"):
            INVENTORY.validate_inventory(duplicate, known_hosts)
        detached = copy.deepcopy(candidate)
        detached["all"]["children"]["management_servers"]["hosts"]["verda-mgmt-server-03"]["attached_device_id"] = "other"
        with self.assertRaisesRegex(ValueError, "attachment continuity"):
            INVENTORY.validate_inventory(detached, known_hosts)

    def test_collector_rejects_duplicate_yaml_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = pathlib.Path(directory) / "inventory.yml"
            inventory.write_text("all:\n  all: duplicate\n", encoding="utf-8")
            with self.assertRaises(COLLECTOR.CollectionError):
                COLLECTOR.read_inventory(inventory)

    def test_etcd_collector_proves_nonleader_from_fixed_topology(self) -> None:
        members = {"members": [{"name": name} for name in COLLECTOR.NODES]}
        statuses = []
        for index, name in enumerate(COLLECTOR.NODES, start=1):
            statuses.append({
                "Endpoint": f"https://{COLLECTOR.WG_ADDRESSES[name]}:2379",
                "Status": {"header": {"member_id": index}, "leader": 1},
            })
        facts = COLLECTOR.etcd_facts(statuses, members, "verda-mgmt-server-03")
        self.assertTrue(facts["selected_node_is_not_current_etcd_leader"])
        self.assertEqual(facts["etcd_healthy_members"], 3)

    def test_collectors_reject_empty_longhorn_and_argo_sets(self) -> None:
        healthy_nodes = {"items": [{"status": {"conditions": [
            {"type": "Ready", "status": "True"}, {"type": "Schedulable", "status": "True"},
        ]}} for _ in range(3)]}
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "volume set is empty"):
            COLLECTOR.longhorn_facts(healthy_nodes, {"items": []})
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "application set is empty"):
            COLLECTOR.argo_facts({"items": []})

    def test_capacity_parser_computes_memory_and_worst_two(self) -> None:
        nodes = {"items": []}
        for index, cpu in enumerate(("6793m", "7000m", "7100m"), start=1):
            nodes["items"].append({
                "metadata": {"name": f"verda-mgmt-server-{index:02d}"},
                "status": {
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "allocatable": {"cpu": cpu, "memory": f"{13 + index}Gi"},
                },
            })
        ready, cpu, memory = COLLECTOR.ready_nodes(nodes)
        self.assertEqual(ready, 3)
        self.assertEqual(sum(sorted(cpu.values())[:2]), 13793)
        self.assertEqual(sum(sorted(memory.values())[:2]), 29 * 1024**3)

    def test_fixed_collector_uses_verified_known_hosts_and_survivor_for_etcd(self) -> None:
        class FakeRunner:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, argv: list[str], *, stdin: bytes | None = None) -> bytes:
                self.commands.append(argv)
                rendered = " ".join(argv)
                if "endpoint status" in rendered:
                    return json.dumps([{
                        "Endpoint": f"https://{COLLECTOR.WG_ADDRESSES[name]}:2379",
                        "Status": {"header": {"member_id": index}, "leader": 1},
                    } for index, name in enumerate(COLLECTOR.NODES, start=1)]).encode()
                if "member list" in rendered:
                    return json.dumps({"members": [{"name": name} for name in COLLECTOR.NODES]}).encode()
                return b"verified"

            def json(self, argv: list[str]) -> object:
                self.commands.append(argv)
                rendered = " ".join(argv)
                if "get nodes -o json" in rendered and "longhorn-system" not in rendered:
                    return {"items": [{
                        "metadata": {"name": name},
                        "status": {
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "allocatable": {"cpu": "7000m", "memory": "28Gi"},
                        },
                    } for name in COLLECTOR.NODES]}
                if argv and argv[0] == "cilium":
                    return {"errors": [], "warnings": [], "cluster": {"desired": 3, "ready": 3}}
                if "nodes.longhorn.io" in rendered:
                    return {"items": [{"status": {"conditions": [
                        {"type": "Ready", "status": "True"},
                        {"type": "Schedulable", "status": "True"},
                    ]}} for _ in range(3)]}
                if "volumes.longhorn.io" in rendered:
                    return {"items": [{"status": {"robustness": "healthy"}}]}
                if "applications.argoproj.io" in rendered:
                    return {"items": [{"status": {
                        "health": {"status": "Healthy"}, "sync": {"status": "Synced"},
                    }}]}
                if "etcd-snapshot ls" in rendered:
                    return {"items": [{
                        "spec": {"location": "s3://withheld/phase6.zip", "snapshotName": "phase6.zip"},
                        "status": {"readyToUse": True, "size": "1024", "creationTime": NOW.isoformat()},
                    }]}
                if "statefulsets" in rendered:
                    return {"items": []}
                raise AssertionError(rendered)

        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            inventory = external / "inventory.yml"
            known = external / "known_hosts"
            known.write_text("verified host keys", encoding="utf-8")
            value = self.canonical_inventory()
            for host in value["all"]["children"]["management_servers"]["hosts"].values():
                host["ansible_ssh_private_key_file"] = "/tmp/phase3-ssh-key"
                host["ansible_ssh_common_args"] = (
                    "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                    f"-o UserKnownHostsFile={known}"
                )
            inventory.write_text(yaml.safe_dump(value), encoding="utf-8")
            runner = FakeRunner()
            facts = COLLECTOR.command_set(
                runner, external / "kubeconfig", inventory,
                "verda-mgmt-server-03", "verda-mgmt-server-01", "preflight",
                now=NOW,
            )
            key_checks = [command for command in runner.commands if command[0] == "ssh-keygen"]
            ssh_commands = [command for command in runner.commands if command[0] == "ssh"]
            self.assertEqual(len(key_checks), 3)
            self.assertTrue(all(str(known) in command for command in key_checks))
            self.assertTrue(all("root@192.0.2.1" in command for command in ssh_commands))
            self.assertTrue(all(f"UserKnownHostsFile={known}" in command for command in ssh_commands))
            self.assertEqual(facts["worst_two_allocatable_memory_bytes"], 56 * 1024**3)
            self.assertTrue(facts["etcd_off_cluster_snapshot_verified"])

    def test_collector_report_is_source_identity_freshness_and_fact_hash_bound(self) -> None:
        facts = {
            "ready_nodes": 3, "etcd_members": 3, "etcd_healthy_members": 3, "etcd_quorum": True,
            "selected_node_is_not_current_etcd_leader": True, "cilium_ready_nodes": 3,
            "cilium_connectivity": True, "longhorn_ready_nodes": 3,
            "longhorn_schedulable_nodes": 3, "longhorn_healthy_volumes": True,
            "longhorn_degraded_volumes": 0, "argocd_all_healthy_synced": True,
            "drain_server_dry_run": True, "etcd_off_cluster_snapshot_verified": True,
            "data_recovery_point_verified": True,
        }
        report = {
            "schema_version": 1, "collector": "phase6-management-resize-v1",
            "collector_sha256": RESIZE.digest_file(COLLECTOR_SCRIPT), "stage": "preflight",
            "phase": 6, "cluster": "management", "integrated_commit": COMMIT,
            "operation_id": "0" * 64, "node": "03", "survivor_node": "01",
            "direction": "resize", "captured_at": NOW.isoformat(), "facts": facts,
            "facts_sha256": RESIZE.canonical_digest(facts), "command_fingerprints": ["1" * 64] * 8,
            "input_fingerprints": {"inventory_sha256": "2" * 64, "host_trust_sha256": "3" * 64},
        }
        RESIZE.assert_trusted_collector_report(
            report, repository=ROOT, integrated_commit=COMMIT, operation_id="0" * 64,
            node="03", survivor="01", direction="resize", stage="preflight", now=NOW,
            freshness_seconds=600,
        )
        tampered = copy.deepcopy(report)
        tampered["facts"]["ready_nodes"] = 2
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "facts digest"):
            RESIZE.assert_trusted_collector_report(
                tampered, repository=ROOT, integrated_commit=COMMIT, operation_id="0" * 64,
                node="03", survivor="01", direction="resize", stage="preflight", now=NOW,
                freshness_seconds=600,
            )
        tampered = copy.deepcopy(report)
        tampered["collector_sha256"] = "f" * 64
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "provenance"):
            RESIZE.assert_trusted_collector_report(
                tampered, repository=ROOT, integrated_commit=COMMIT, operation_id="0" * 64,
                node="03", survivor="01", direction="resize", stage="preflight", now=NOW,
                freshness_seconds=600,
            )

    def test_recovery_etcd_is_two_survivors_and_snapshot_must_be_operation_fresh(self) -> None:
        members = {"members": [{"name": name} for name in COLLECTOR.NODES]}
        statuses = [{
            "Endpoint": f"https://{COLLECTOR.WG_ADDRESSES[name]}:2379",
            "Status": {"header": {"member_id": index}, "leader": 1},
        } for index, name in enumerate(COLLECTOR.NODES[:2], start=1)]
        facts = COLLECTOR.etcd_facts(statuses, members, "verda-mgmt-server-03", "recovery")
        self.assertEqual(facts["etcd_healthy_members"], 2)
        with self.assertRaises(COLLECTOR.CollectionError):
            COLLECTOR.etcd_facts(statuses + [{
                "Endpoint": "https://10.250.0.13:2379",
                "Status": {"header": {"member_id": 3}, "leader": 1},
            }], members, "verda-mgmt-server-03", "recovery")
        stale = {"items": [{
            "spec": {"location": "s3://withheld/phase6.zip", "snapshotName": "phase6.zip"},
            "status": {"readyToUse": True, "size": "1024",
                       "creationTime": (NOW - dt.timedelta(hours=1)).isoformat()},
        }]}
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "structured off-cluster"):
            COLLECTOR.snapshot_facts(stale, now=NOW, freshness_seconds=600)


class OperationJournalTests(unittest.TestCase):
    def paths(self, external: pathlib.Path, operation_id: str) -> tuple[pathlib.Path, pathlib.Path]:
        control = external / "phase6-resize-control"
        return control / f"phase6-resize-operation-{operation_id}.json", control / "phase6-resize-operation.lock"

    def test_prepared_applying_adopted_applied_is_atomic_and_generation_bound(self) -> None:
        operation = "1" * 64
        with tempfile.TemporaryDirectory() as directory:
            journal_path, lease_path = self.paths(pathlib.Path(directory), operation)
            journal = RESIZE.OperationJournal(
                repository=ROOT, journal_path=journal_path, lease_path=lease_path,
                operation_id=operation, integrated_commit=COMMIT,
            )
            with journal:
                prepared = journal.prepare(
                    expected_generation=0, node="03", direction="resize", plan_sha256="2" * 64,
                    review_sha256="3" * 64, prepare_sha256="4" * 64,
                    state_lineage_sha256="5" * 64, state_serial_before=10, captured_at=NOW.isoformat(),
                )
                self.assertEqual((prepared["state"], prepared["generation"]), ("PREPARED", 1))
                applying = journal.begin_apply(expected_generation=1, captured_at=NOW.isoformat())
                self.assertEqual((applying["state"], applying["generation"]), ("APPLYING", 2))
                adopted = journal.adopt_applying(
                    expected_generation=2, plan_sha256="2" * 64,
                    state_lineage_sha256="5" * 64, state_serial_before=10,
                    captured_at=(NOW + dt.timedelta(seconds=1)).isoformat(),
                )
                self.assertEqual(adopted["generation"], 3)
                applied = journal.record_apply_receipt(
                    expected_generation=3, receipt_sha256="6" * 64,
                    captured_at=(NOW + dt.timedelta(seconds=2)).isoformat(),
                )
                self.assertEqual((applied["state"], applied["generation"]), ("APPLIED", 4))
                with self.assertRaisesRegex(RESIZE.ResizeRefused, "PREPARED"):
                    journal.begin_apply(expected_generation=1, captured_at=NOW.isoformat())
            self.assertEqual(json.loads(journal_path.read_text(encoding="utf-8"))["state"], "APPLIED")

    def test_crash_adoption_mismatch_and_parallel_lease_are_refused(self) -> None:
        operation = "7" * 64
        with tempfile.TemporaryDirectory() as directory:
            journal_path, lease_path = self.paths(pathlib.Path(directory), operation)
            first = RESIZE.OperationJournal(
                repository=ROOT, journal_path=journal_path, lease_path=lease_path,
                operation_id=operation, integrated_commit=COMMIT,
            )
            second = RESIZE.OperationJournal(
                repository=ROOT, journal_path=journal_path, lease_path=lease_path,
                operation_id=operation, integrated_commit=COMMIT,
            )
            with first:
                first.prepare(
                    expected_generation=0, node="03", direction="resize", plan_sha256="2" * 64,
                    review_sha256="3" * 64, prepare_sha256="4" * 64,
                    state_lineage_sha256="5" * 64, state_serial_before=10, captured_at=NOW.isoformat(),
                )
                first.begin_apply(expected_generation=1, captured_at=NOW.isoformat())
                with self.assertRaisesRegex(RESIZE.ResizeRefused, "OS-exclusive"):
                    second.__enter__()
                with self.assertRaisesRegex(RESIZE.ResizeRefused, "does not match"):
                    first.adopt_applying(
                        expected_generation=2, plan_sha256="8" * 64,
                        state_lineage_sha256="5" * 64, state_serial_before=10,
                        captured_at=NOW.isoformat(),
                    )

    def test_applied_resize_does_not_block_separate_immediate_rollback_journal(self) -> None:
        resize_operation, rollback_operation = "a" * 64, "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            resize_path, lease_path = self.paths(external, resize_operation)
            with RESIZE.OperationJournal(
                repository=ROOT, journal_path=resize_path, lease_path=lease_path,
                operation_id=resize_operation, integrated_commit=COMMIT,
            ) as journal:
                journal.prepare(
                    expected_generation=0, node="03", direction="resize", plan_sha256="2" * 64,
                    review_sha256="3" * 64, prepare_sha256="4" * 64,
                    state_lineage_sha256="5" * 64, state_serial_before=10, captured_at=NOW.isoformat(),
                )
                journal.begin_apply(expected_generation=1, captured_at=NOW.isoformat())
                journal.record_apply_receipt(
                    expected_generation=2, receipt_sha256="6" * 64, captured_at=NOW.isoformat(),
                )
            rollback_path, _ = self.paths(external, rollback_operation)
            with RESIZE.OperationJournal(
                repository=ROOT, journal_path=rollback_path, lease_path=lease_path,
                operation_id=rollback_operation, integrated_commit=COMMIT,
            ) as rollback:
                prepared = rollback.prepare(
                    expected_generation=0, node="03", direction="rollback", plan_sha256="7" * 64,
                    review_sha256="8" * 64, prepare_sha256="9" * 64,
                    state_lineage_sha256="5" * 64, state_serial_before=11, captured_at=NOW.isoformat(),
                )
                self.assertEqual(prepared["direction"], "rollback")


class ActivationIntegrationTests(unittest.TestCase):
    class FakeAdapter:
        def __init__(self, inventory_text: str, known_hosts: pathlib.Path, *, crash_apply: bool = False) -> None:
            self.inventory_text = inventory_text
            self.known_hosts = known_hosts
            self.crash_apply = crash_apply
            self.calls: list[str] = []

        def run_container(self, command: list[str], receipt: dict) -> dict:
            self.calls.append(f"container:{receipt['mode']}")
            return {
                "schema_version": 1, "status": "PINNED_CONTAINER_COMPLETE",
                "mode": receipt["mode"], "node": receipt["node"],
                "survivor_node": receipt["survivor_node"],
                "command_receipt_sha256": RESIZE.canonical_digest(receipt),
                "raw_values_recorded": False,
            }

        def phase2_apply(self, *, saved_plan: pathlib.Path, plan_sha256: str,
                         lineage_sha256: str, state_serial: int, operation_id: str) -> dict:
            self.calls.append("phase2:apply")
            if self.crash_apply:
                raise RESIZE.ResizeRefused("simulated receipt-loss crash")
            return {
                "schema_version": 1, "status": "APPLY_COMPLETE_RECOVERY_REQUIRED",
                "operation_id": operation_id, "plan_sha256": plan_sha256,
                "state_lineage_sha256": lineage_sha256, "state_serial_before": state_serial,
                "state_serial_after": state_serial + 1, "raw_values_recorded": False,
            }

        def phase2_state(self, *, lineage_sha256: str, operation_id: str) -> dict:
            self.calls.append("phase2:state")
            return {
                "schema_version": 1, "status": "STATE_RECEIPT", "operation_id": operation_id,
                "state_lineage_sha256": lineage_sha256, "state_serial": STATE_SERIAL + 1,
                "raw_values_recorded": False,
            }

        def phase2_output(self, *, inventory_output: pathlib.Path, known_hosts: pathlib.Path,
                          lineage_sha256: str, state_serial: int, operation_id: str) -> dict:
            self.calls.append("phase2:output")
            inventory_output.write_text(self.inventory_text, encoding="utf-8")
            return {
                "schema_version": 1, "status": "STRICT_INVENTORY_CREATED_REVIEW_REQUIRED",
                "operation_id": operation_id, "state_lineage_sha256": lineage_sha256,
                "state_serial": state_serial, "inventory_sha256": RESIZE.digest_file(inventory_output),
                "known_hosts_sha256": RESIZE.digest_file(known_hosts),
                "private_key_public_sha256": "9" * 64, "raw_values_recorded": False,
            }

        def phase2_no_drift(self, *, lineage_sha256: str, state_serial: int,
                            operation_id: str) -> dict:
            self.calls.append("phase2:no-drift")
            return {
                "schema_version": 1, "status": "ZERO_DRIFT_VERIFIED",
                "operation_id": operation_id, "state_lineage_sha256": lineage_sha256,
                "state_serial": state_serial, "terraform_zero_drift": True,
                "raw_values_recorded": False,
            }

        def collect(self, command: list[str]) -> dict:
            stage = (
                "preflight" if "--stage preflight" in command[-1]
                else "recovery" if "--stage recovery" in command[-1]
                else "postflight"
            )
            self.calls.append(f"collector:{stage}")
            mounts = {
                value.rsplit(":", 2)[1]: pathlib.Path(value.rsplit(":", 2)[0])
                for index, value in enumerate(command)
                if index > 0 and command[index - 1] == "--volume"
            }
            if stage == "recovery":
                facts = {
                    "ready_nodes": 2, "etcd_members": 3, "etcd_healthy_members": 2,
                    "etcd_quorum": True, "surviving_ready_nodes": 2,
                    "surviving_etcd_healthy_members": 2, "replacement_not_ready": True,
                    "partial_inventory_refreshed": True, "wireguard_peer_inputs_complete": True,
                }
                fingerprints = ["1" * 64] * 6
            else:
                facts = {
                    "ready_nodes": 3, "etcd_members": 3, "etcd_healthy_members": 3,
                    "etcd_quorum": True, "cilium_ready_nodes": 3, "cilium_connectivity": True,
                    "longhorn_ready_nodes": 3, "longhorn_schedulable_nodes": 3,
                    "longhorn_healthy_volumes": True, "longhorn_degraded_volumes": 0,
                    "longhorn_rebuild_complete": True, "argocd_all_healthy_synced": True,
                    "minimum_observed_per_node_cpu_millicores": 7000,
                    "minimum_observed_per_node_memory_bytes": 30_000_000_000,
                    "worst_two_allocatable_cpu_millicores": 14000,
                    "worst_two_allocatable_memory_bytes": 60_000_000_000,
                }
                if stage == "preflight":
                    facts.update({
                        "selected_node_is_not_current_etcd_leader": True,
                        "drain_server_dry_run": True,
                        "etcd_off_cluster_snapshot_verified": True,
                        "data_recovery_point_verified": True,
                    })
                fingerprints = ["1" * 64] * 8
            return {
                "schema_version": 1, "collector": "phase6-management-resize-v1",
                "collector_sha256": RESIZE.digest_file(COLLECTOR_SCRIPT), "stage": stage,
                "phase": 6, "cluster": "management", "integrated_commit": COMMIT,
                "operation_id": self.operation_id, "node": "03", "survivor_node": "01",
                "direction": self.direction, "captured_at": NOW.isoformat(), "facts": facts,
                "facts_sha256": RESIZE.canonical_digest(facts), "command_fingerprints": fingerprints,
                "input_fingerprints": {
                    "inventory_sha256": RESIZE.digest_file(mounts["/run/config/phase6-inventory.yml"]),
                    "host_trust_sha256": RESIZE.digest_file(mounts["/run/config/known_hosts"]),
                },
            }

    def inputs(self, external: pathlib.Path) -> dict[str, pathlib.Path | str]:
        runner = PinnedRecoveryRunnerTests()
        paths = runner.inputs(external)
        kubeconfig = external / "kubeconfig"
        kubeconfig.write_text("fake credential material", encoding="utf-8")
        if os.name != "nt":
            kubeconfig.chmod(0o600)
        return {**paths, "inventory_text": paths["inventory"].read_text(encoding="utf-8"), "kubeconfig": kubeconfig}

    def execute(self, external: pathlib.Path, adapter: "ActivationIntegrationTests.FakeAdapter",
                *, operation: str, direction: str = "resize") -> dict:
        contract_path = external / "contract.json"
        progress_path = external / "progress.json"
        saved_plan = external / f"{direction}.tfplan"
        contract_path.write_text(json.dumps(active_contract()), encoding="utf-8")
        if not progress_path.exists():
            progress_path.write_text(json.dumps(progress()), encoding="utf-8")
        saved_plan.write_bytes(direction.encode())
        dummy = {}
        for name in ("preflight", "review", "lease", "cost", "capacity", "collector"):
            path = external / f"{name}.json"
            path.write_text("{}", encoding="utf-8")
            dummy[name] = path
        inputs = self.inputs(external)
        adapter.inventory_text = str(inputs["inventory_text"])
        adapter.known_hosts = inputs["known"]  # type: ignore[assignment]
        adapter.operation_id = operation
        adapter.direction = direction
        preflight_command = RESIZE.build_phase6_collector_command(
            repository=ROOT, stage="preflight", node="03", survivor="01", direction=direction,
            operation_id=operation, integrated_commit=COMMIT, kubeconfig_path=inputs["kubeconfig"],
            inventory_path=inputs["inventory"], private_key_path=inputs["private"],
            known_hosts_path=inputs["known"],
        )
        dummy["collector"].write_text(json.dumps(adapter.collect(preflight_command)), encoding="utf-8")
        with mock.patch.object(RESIZE, "assert_clean_reviewed_worktree"), mock.patch.object(
            RESIZE, "admission", return_value={"plan_sha256": RESIZE.digest_file(saved_plan)}
        ):
            return RESIZE.execute_reviewed_apply(
                repository=ROOT, contract_path=contract_path, progress_path=progress_path,
                saved_plan=saved_plan, preflight_path=dummy["preflight"], review_path=dummy["review"],
                review_lease_path=dummy["lease"], cost_path=dummy["cost"],
                capacity_path=dummy["capacity"], collector_path=dummy["collector"],
                control_root=external / "phase6-resize-control", inventory_path=inputs["inventory"],
                runtime_vars_path=inputs["runtime"], private_key_path=inputs["private"],
                public_key_path=inputs["public"], known_hosts_path=inputs["known"],
                operation_id=operation, survivor="01", direction=direction,
                kubeconfig_path=inputs["kubeconfig"],
                state_lineage_sha256=LINEAGE, state_serial=STATE_SERIAL,
                git_commit=COMMIT, adapter=adapter, now=NOW,
            )

    def test_fake_apply_recovery_postflight_is_atomic_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            adapter = self.FakeAdapter("", external / "known_hosts")
            operation = "4" * 64
            applied = self.execute(external, adapter, operation=operation)
            self.assertEqual(applied["status"], "APPLIED_RECOVERY_REQUIRED")
            inputs = self.inputs(external)
            adapter.inventory_text = str(inputs["inventory_text"])
            adapter.known_hosts = inputs["known"]  # type: ignore[assignment]
            with mock.patch.object(RESIZE, "assert_clean_reviewed_worktree"):
                completed = RESIZE.recover_reviewed_node(
                    repository=ROOT, contract_path=external / "contract.json",
                    progress_path=external / "progress.json", control_root=external / "phase6-resize-control",
                    operation_id=operation, survivor="01", inventory_output=external / "recovered-inventory.yml",
                    runtime_vars_path=inputs["runtime"], private_key_path=inputs["private"],
                    public_key_path=inputs["public"], known_hosts_path=inputs["known"],
                    kubeconfig_path=inputs["kubeconfig"], git_commit=COMMIT, adapter=adapter, now=NOW,
                )
            self.assertEqual(completed["status"], "NODE_COMPLETE")
            self.assertEqual(json.loads((external / "progress.json").read_text())["completed_resize_nodes"], ["03"])

    def test_receipt_loss_crash_is_adopted_and_immediate_rollback_is_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            crash = self.FakeAdapter("", external / "known_hosts", crash_apply=True)
            operation = "6" * 64
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "receipt-loss"):
                self.execute(external, crash, operation=operation)
            crash.crash_apply = False
            with mock.patch.object(RESIZE, "assert_clean_reviewed_worktree"):
                adopted = RESIZE.adopt_reviewed_apply(
                    repository=ROOT, contract_path=external / "contract.json",
                    progress_path=external / "progress.json", control_root=external / "phase6-resize-control",
                    operation_id=operation, git_commit=COMMIT, adapter=crash, now=NOW,
                )
            self.assertEqual(adopted["status"], "APPLY_ADOPTED_RECOVERY_REQUIRED")
            rollback = self.FakeAdapter("", external / "known_hosts")
            rolled = self.execute(external, rollback, operation="7" * 64, direction="rollback")
            self.assertEqual((rolled["node"], rolled["direction"]), ("03", "rollback"))


class PinnedRecoveryRunnerTests(unittest.TestCase):
    def inputs(self, external: pathlib.Path) -> dict[str, pathlib.Path]:
        inventory = external / "inventory.yml"
        runtime = external / "runtime.json"
        private = external / "id_ed25519"
        public = external / "id_ed25519.pub"
        known = external / "known_hosts"
        hosts = {}
        for index in range(1, 4):
            name = f"verda-mgmt-server-{index:02d}"
            hosts[name] = {
                "ansible_host": f"192.0.2.{index}", "ansible_user": "root", "node_name": name,
                "role": "server", "internal_ip": f"10.0.0.{index}", "wireguard_ip": f"10.250.0.1{index}",
                "data_volume_id": f"volume-{index}", "attached_device_id": f"volume-{index}",
                "data_volume_size_gib": 100, "ansible_ssh_private_key_file": "/tmp/phase3-ssh-key",
                "ansible_ssh_common_args": (
                    "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                    "-o UserKnownHostsFile=/run/config/known_hosts"
                ),
            }
        inventory.write_text(
            yaml.safe_dump({"all": {"children": {"management_servers": {"hosts": hosts}}}}, sort_keys=True),
            encoding="utf-8",
        )
        runtime.write_text(json.dumps({
            "phase3_admin_cidrs_v4": ["192.0.2.0/24"], "phase4_cluster_firewall_enabled": True,
        }), encoding="utf-8")
        private.write_text("not-a-real-private-key", encoding="utf-8")
        if os.name != "nt":
            private.chmod(0o600)
        public.write_text(
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA phase6\n",
            encoding="utf-8",
        )
        known.write_text("hashed known-host fixture\n", encoding="utf-8")
        return {"inventory": inventory, "runtime": runtime, "private": private, "public": public, "known": known}

    def controls(self, external: pathlib.Path, mode: str) -> dict[str, pathlib.Path]:
        control = external / "phase6-resize-control"
        control.mkdir(exist_ok=True)
        operation = "0" * 64
        contract = external / "active-contract.json"
        journal = control / f"phase6-resize-operation-{operation}.json"
        authorization = control / f"phase6-resize-authorization-{operation}-{mode}.json"
        contract.write_text(json.dumps(active_contract()), encoding="utf-8")
        journal.write_text(json.dumps({
            "schema_version": 1, "phase": 6, "integrated_commit": COMMIT,
            "operation_id": operation, "node": "03", "direction": "resize",
            "state": "PREPARED" if mode == "prepare" else "APPLIED",
        }), encoding="utf-8")
        RESIZE.create_operation_authorization(
            path=authorization, contract_path=contract, journal_path=journal,
            integrated_commit=COMMIT, operation_id=operation, node="03",
            direction="resize", mode=mode, now=NOW,
        )
        return {"contract": contract, "journal": journal, "authorization": authorization}

    def build(self, external: pathlib.Path, mode: str = "recover") -> tuple[list[str], dict]:
        paths = self.inputs(external)
        controls = self.controls(external, mode)
        return RESIZE.build_phase6_docker_command(
            repository=ROOT, mode=mode, node="03", survivor="01",
            inventory_path=paths["inventory"], runtime_vars_path=paths["runtime"],
            private_key_path=paths["private"], public_key_path=paths["public"],
            known_hosts_path=paths["known"], contract_path=controls["contract"],
            journal_path=controls["journal"], authorization_path=controls["authorization"],
            integrated_commit=COMMIT, operation_id="0" * 64, direction="resize",
        )

    def test_recovery_uses_exact_pinned_container_mounts_env_and_workdir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command, receipt = self.build(pathlib.Path(directory))
            rendered = " ".join(command)
            self.assertEqual(command[:3], ["docker", "run", "--rm"])
            self.assertIn("verda-platform-quality:phase1-2026-08-16", command)
            self.assertIn("/run/secrets/phase3_ssh_key.pub:ro", rendered)
            self.assertIn("/run/source/phase4-ssh-key:ro", rendered)
            self.assertIn("/run/config/known_hosts:ro", rendered)
            self.assertIn("/workspace/infra/ansible", command)
            self.assertIn("@inventories/group_vars/management_servers.yml", rendered)
            self.assertIn("@/run/config/phase6-runtime.json", rendered)
            environments = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--env"]
            self.assertEqual(tuple(environments), RESIZE.RECOVERY_ENV_ALLOWLIST)
            self.assertNotIn("not-a-real-private-key", rendered + json.dumps(receipt))
            self.assertEqual(receipt["status"], "PINNED_OPERATION_COMMAND_BOUND")

    def test_prepare_uses_only_bounded_prepare_playbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command, receipt = self.build(pathlib.Path(directory), "prepare")
            rendered = " ".join(command)
            self.assertIn("playbooks/prepare-management-node-resize.yml", rendered)
            self.assertIn("phase6_prepare_survivor=verda-mgmt-server-01", rendered)
            self.assertNotIn("recover-resized-management-node.yml", rendered)
            self.assertEqual(receipt["mode"], "prepare")

    def test_runtime_extra_field_and_ssh_downgrade_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            external = pathlib.Path(directory)
            paths = self.inputs(external)
            runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
            runtime["unexpected"] = True
            paths["runtime"].write_text(json.dumps(runtime), encoding="utf-8")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "exact checked schema"):
                RESIZE.canonical_recovery_inputs(
                    repository=ROOT, inventory_path=paths["inventory"], runtime_vars_path=paths["runtime"],
                    private_key_path=paths["private"], public_key_path=paths["public"], known_hosts_path=paths["known"],
                )
            paths = self.inputs(external)
            inventory = paths["inventory"].read_text(encoding="utf-8").replace(
                "StrictHostKeyChecking=yes", "StrictHostKeyChecking=accept-new"
            )
            paths["inventory"].write_text(inventory, encoding="utf-8")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "SSH"):
                RESIZE.canonical_recovery_inputs(
                    repository=ROOT, inventory_path=paths["inventory"], runtime_vars_path=paths["runtime"],
                    private_key_path=paths["private"], public_key_path=paths["public"], known_hosts_path=paths["known"],
                )

    def test_hardlinked_recovery_inputs_are_rejected_before_command_construction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.inputs(pathlib.Path(directory))
            paths["known"].unlink()
            os.link(paths["private"], paths["known"])
            controls = self.controls(pathlib.Path(directory), "recover")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "file identity"):
                RESIZE.build_phase6_docker_command(
                    repository=ROOT, mode="recover", node="03", survivor="01",
                    inventory_path=paths["inventory"], runtime_vars_path=paths["runtime"],
                    private_key_path=paths["private"], public_key_path=paths["public"],
                    known_hosts_path=paths["known"], contract_path=controls["contract"],
                    journal_path=controls["journal"], authorization_path=controls["authorization"],
                    integrated_commit=COMMIT, operation_id="0" * 64, direction="resize",
                )


if __name__ == "__main__":
    unittest.main()
