#!/usr/bin/env python3
"""Focused positive and negative tests for Phase 6 serial resize admission."""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "management-node-resize.py"
CONTRACT_PATH = ROOT / "config" / "phase6-management-resize.json"
SPEC = importlib.util.spec_from_file_location("phase6_resize", SCRIPT)
assert SPEC and SPEC.loader
RESIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESIZE)
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
    return {
        "schema_version": 1,
        "integrated_commit": COMMIT,
        "completed_resize_nodes": resized or [],
        "completed_rollback_nodes": rolled_back or [],
        "in_flight_node": in_flight,
        "in_flight_direction": "resize" if in_flight else None,
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
        resized = RESIZE.assert_plan(plan(), active_contract(), "03", "resize")
        rolled_back = RESIZE.assert_plan(plan("01", "rollback"), active_contract(), "01", "rollback")
        self.assertEqual(resized["target_instance_type"], "CPU.8V.32G")
        self.assertEqual(rolled_back["target_instance_type"], "CPU.4V.16G")

    def test_extra_change_is_rejected(self) -> None:
        candidate = plan()
        candidate["resource_changes"].append(copy.deepcopy(candidate["resource_changes"][0]))
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "exactly one"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize")

    def test_wrong_node_or_shape_is_rejected(self) -> None:
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_plan(plan("02"), active_contract(), "03", "resize")
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["instance_type"] = "CPU.16V.64G"
        with self.assertRaises(RESIZE.ResizeRefused):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize")

    def test_data_volume_or_ssh_key_change_is_rejected(self) -> None:
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["existing_volumes"] = ["other"]
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "data volume"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize")
        candidate = plan()
        candidate["resource_changes"][0]["change"]["after"]["ssh_key_ids"] = ["other"]
        with self.assertRaisesRegex(RESIZE.ResizeRefused, "SSH key"):
            RESIZE.assert_plan(candidate, active_contract(), "03", "resize")


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

    def test_recovery_admission_binds_strict_external_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as repo_name, tempfile.TemporaryDirectory() as external_name:
            repo = pathlib.Path(repo_name)
            external = pathlib.Path(external_name)
            contract = active_contract()
            contract_path = repo / "contract.json"
            progress_path = repo / "progress.json"
            recovery_path = repo / "recovery.json"
            lease_path = repo / "lease.json"
            inventory_path = external / "inventory.yml"
            private_key = external / "id_ed25519"
            known_hosts = external / "known_hosts"
            runtime_vars = external / "runtime.yml"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            in_flight = progress(in_flight="03")
            progress_path.write_text(json.dumps(in_flight), encoding="utf-8")
            recovery = {
                "schema_version": 1, "phase": 6, "cluster": "management", "integrated_commit": COMMIT,
                "node": "03", "captured_at": NOW.isoformat(), "checks": contract["required_recovery"],
            }
            recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
            lease_path.write_text(json.dumps({
                "schema_version": 1, "phase": 6, "integrated_commit": COMMIT, "owner_digest": OWNER,
                "writes_allowed": True, "expires_at": (NOW + dt.timedelta(minutes=5)).isoformat(),
            }), encoding="utf-8")
            private_key.write_text("opaque", encoding="utf-8")
            known_hosts.write_text("hashed-host-key", encoding="utf-8")
            runtime_vars.write_text("---\nphase3_admin_cidrs_v4: [192.0.2.1/32]\n", encoding="utf-8")
            host_lines = []
            for ordinal in ("01", "02", "03"):
                host_lines.append(f"      verda-mgmt-server-{ordinal}:\n")
            inventory_path.write_text(
                "---\nall:\n  children:\n    management_servers:\n      hosts:\n"
                + "".join(host_lines)
                + f"ansible_ssh_private_key_file: {private_key.resolve()}\n"
                + f"ansible_ssh_common_args: -o StrictHostKeyChecking=yes -o UserKnownHostsFile={known_hosts.resolve()}\n",
                encoding="utf-8",
            )
            summary, command = RESIZE.recovery_admission(
                contract_path=contract_path, progress_path=progress_path, recovery_path=recovery_path,
                lease_path=lease_path, direction="resize", git_commit=COMMIT, repository=repo,
                inventory_path=inventory_path, private_key_path=private_key, known_hosts_path=known_hosts,
                runtime_vars_path=runtime_vars, now=NOW,
            )
            self.assertEqual(summary["node"], "03")
            self.assertIn("recover-resized-management-node.yml", " ".join(command))
            unsafe = inventory_path.read_text().replace("StrictHostKeyChecking=yes", "StrictHostKeyChecking=accept-new")
            inventory_path.write_text(unsafe, encoding="utf-8")
            with self.assertRaisesRegex(RESIZE.ResizeRefused, "host-key"):
                RESIZE.recovery_admission(
                    contract_path=contract_path, progress_path=progress_path, recovery_path=recovery_path,
                    lease_path=lease_path, direction="resize", git_commit=COMMIT, repository=repo,
                    inventory_path=inventory_path, private_key_path=private_key, known_hosts_path=known_hosts,
                    runtime_vars_path=runtime_vars, now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
