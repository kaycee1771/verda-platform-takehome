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
            "plan_sha256": "1" * 64, "preflight_sha256": "2" * 64, "contract_sha256": "3" * 64,
            "author_digest": AUTHOR, "reviewer_digest": AUTHOR, "security_approved": True, "capacity_approved": True,
        }
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "must differ"):
            RESIZE.assert_review(review, COMMIT, "03", "resize", "1" * 64, "2" * 64, "3" * 64)


class AdmissionTests(unittest.TestCase):
    def test_full_admission_is_hash_bound_and_identity_free(self) -> None:
        with tempfile.TemporaryDirectory() as repo_name, tempfile.TemporaryDirectory() as external_name:
            repo = pathlib.Path(repo_name)
            external = pathlib.Path(external_name)
            contract = active_contract()
            contract_path = repo / "contract.json"
            progress_path = repo / "progress.json"
            preflight_path = repo / "preflight.json"
            review_path = repo / "review.json"
            lease_path = repo / "lease.json"
            plan_path = external / "node03.tfplan"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            progress_path.write_text(json.dumps(progress()), encoding="utf-8")
            preflight = {
                "schema_version": 1, "phase": 6, "cluster": "management", "integrated_commit": COMMIT,
                "node": "03", "captured_at": NOW.isoformat(), "checks": contract["required_preflight"],
            }
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            plan_path.write_bytes(b"opaque saved terraform plan")
            review = {
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "node": "03", "direction": "resize",
                "plan_sha256": RESIZE.digest_file(plan_path), "preflight_sha256": RESIZE.digest_file(preflight_path),
                "contract_sha256": RESIZE.digest_file(contract_path), "author_digest": AUTHOR,
                "reviewer_digest": REVIEWER, "security_approved": True, "capacity_approved": True,
            }
            review_path.write_text(json.dumps(review), encoding="utf-8")
            lease = {
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "owner_digest": OWNER,
                "writes_allowed": True, "expires_at": (NOW + dt.timedelta(minutes=5)).isoformat(),
            }
            lease_path.write_text(json.dumps(lease), encoding="utf-8")
            summary = RESIZE.admission(
                contract_path=contract_path, progress_path=progress_path, saved_plan=plan_path,
                preflight_path=preflight_path, review_path=review_path, lease_path=lease_path,
                direction="resize", git_commit=COMMIT, repository=repo, now=NOW, plan=plan(),
            )
            rendered = json.dumps(summary)
            self.assertEqual(summary["replacement_count"], 1)
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

    def test_live_recovery_is_unconditionally_disabled(self) -> None:
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "pinned container runner"):
            RESIZE.recovery_admission(
                contract_path=pathlib.Path("unused"), progress_path=pathlib.Path("unused"),
                recovery_path=pathlib.Path("unused"), lease_path=pathlib.Path("unused"),
                direction="resize", git_commit=COMMIT, repository=ROOT,
                inventory_path=pathlib.Path("unused"), private_key_path=pathlib.Path("unused"),
                known_hosts_path=pathlib.Path("unused"), runtime_vars_path=pathlib.Path("unused"), now=NOW,
            )

    def test_cli_exposes_no_mutating_or_recovery_action(self) -> None:
        parser = RESIZE.build_parser()
        choices = next(action.choices for action in parser._actions if getattr(action, "choices", None))
        self.assertEqual(set(choices), {"validate-contract"})
        phase2 = (ROOT / "scripts" / "infra" / "phase2.ps1").read_text()
        self.assertNotIn("phase6-resize-apply", phase2)
        self.assertNotIn("Invoke-Phase6ResizeApply", phase2)


class ProtectedStateSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "scripts" / "infra" / "phase2.ps1").read_text(encoding="utf-8")

    def section(self, start: str, end: str) -> str:
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def test_phase6_has_explicit_plan_and_output_boundaries_only(self) -> None:
        self.assertIn("'phase6-resize-plan'", self.source)
        self.assertIn("'phase6-resize-output'", self.source)
        self.assertNotIn("phase6-resize-apply", self.source)
        self.assertNotIn("Invoke-Phase6ResizeApply", self.source)
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


if __name__ == "__main__":
    unittest.main()
