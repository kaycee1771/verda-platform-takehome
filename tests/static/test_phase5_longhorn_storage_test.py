#!/usr/bin/env python3
"""Credential-free tests for the bounded Phase 5 Longhorn live harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase5" / "longhorn-storage-test.sh"
CONTRACT = ROOT / "scripts" / "phase5" / "longhorn-storage-contract.py"
RUN_ID = "p5st-20260819t120000z-deadbeef"
NAMESPACE = f"longhorn-test-{RUN_ID}"
IMAGE = (
    "quay.io/cilium/alpine-curl:v1.10.0@sha256:"
    "913e8c9f3d960dde03882defa0edd3a919d529c2eb167caa7f54194528bde364"
)


def load_contract():
    spec = importlib.util.spec_from_file_location(
        "phase5_longhorn_storage_contract", CONTRACT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def volume() -> dict:
    return {
        "metadata": {"name": "volume-handle", "uid": "volume-uid"},
        "spec": {"numberOfReplicas": 3},
        "status": {
            "state": "attached",
            "robustness": "healthy",
            "kubernetesStatus": {
                "namespace": NAMESPACE,
                "pvcName": "checksum-data",
                "pvName": "pv-name",
            },
        },
    }


def replicas() -> list[dict]:
    return [
        {
            "metadata": {"name": f"replica-{index}"},
            "spec": {
                "volumeName": "volume-handle",
                "nodeID": f"verda-mgmt-server-{index:02d}",
                "failedAt": "",
                "healthyAt": "2026-08-19T12:00:00Z",
            },
            "status": {"currentState": "running"},
        }
        for index in range(1, 4)
    ]


def pod(name: str, node: str) -> dict:
    return {
        "metadata": {"name": name, "namespace": NAMESPACE},
        "spec": {"nodeName": node, "containers": [{"image": IMAGE}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }


def pvc() -> dict:
    return {
        "metadata": {
            "name": "checksum-data",
            "namespace": NAMESPACE,
            "uid": "pvc-uid",
            "labels": {
                "platform.verda-demo.io/test": "longhorn-reschedule",
                "platform.verda-demo.io/run-id": RUN_ID,
            },
        },
        "spec": {
            "storageClassName": "longhorn-critical",
            "volumeName": "pv-name",
        },
        "status": {"phase": "Bound"},
    }


def pvs() -> dict:
    return {
        "items": [
            {
                "metadata": {"name": "pv-name", "uid": "pv-uid"},
                "spec": {
                    "storageClassName": "longhorn-critical",
                    "persistentVolumeReclaimPolicy": "Retain",
                    "claimRef": {
                        "namespace": NAMESPACE,
                        "name": "checksum-data",
                        "uid": "pvc-uid",
                    },
                    "csi": {
                        "driver": "driver.longhorn.io",
                        "volumeHandle": "volume-handle",
                    },
                },
            }
        ]
    }


class Phase5LonghornStorageTest(unittest.TestCase):
    def test_script_is_mutation_bounded_and_uses_protected_runtime(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("phase5_assert_cluster_runtime", script)
        self.assertIn("PHASE5_CONFIRM_STORAGE_TEST", script)
        self.assertIn("longhorn-critical-reschedule-and-cleanup", script)
        self.assertIn("^p5st-[0-9]{8}t[0-9]{6}z-[a-f0-9]{8}$", script)
        self.assertIn('test_namespace="longhorn-test-${run_id}"', script)
        self.assertIn("platform.verda-demo.io/run-id", script)
        self.assertIn("cleanup_ownership", CONTRACT.read_text(encoding="utf-8"))
        self.assertIn('patch persistentvolume "${pv_name}"', script)
        self.assertIn('persistentVolumeReclaimPolicy":"Delete', script)
        for forbidden in (
            "helm uninstall",
            "delete storageclass",
            "delete volumes.longhorn.io",
            "delete replicas.longhorn.io",
            "delete namespace longhorn-system",
        ):
            self.assertNotIn(forbidden, script.lower())

    def test_script_uses_pinned_fixture_and_deterministic_checksum(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(IMAGE, script)
        self.assertIn(
            "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
            script,
        )
        self.assertIn("dd if=/dev/zero", script)
        self.assertIn("count=4", script)
        self.assertIn("storageClassName: ${storage_class}", script)
        self.assertIn("storage: 1Gi", script)

    def test_reschedule_preserves_claim_and_excludes_source_node(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        delete_writer = script.index("delete pod writer --wait=true")
        create_reader = script.index("kind: Pod", script.index("name: reader") - 100)
        cleanup = script.index("cleanup_test_objects ||")
        self.assertLess(delete_writer, create_reader)
        self.assertLess(create_reader, cleanup)
        self.assertIn("requiredDuringSchedulingIgnoredDuringExecution", script)
        self.assertIn("operator: NotIn", script)
        self.assertIn("values: [${source_node}]", script)
        self.assertNotIn("delete pvc", script.lower())
        self.assertEqual(script.count('patch persistentvolume "${pv_name}"'), 1)
        self.assertLess(
            script.index("wait_for_longhorn_health after"),
            script.index("cleanup_test_objects ||"),
        )

    def test_capacity_and_cleanup_proofs_are_pre_and_post_scoped(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            script.index("capture_capacity pre"), script.index("kind: Namespace")
        )
        self.assertLess(
            script.index("cleanup_test_objects ||"),
            script.index("capture_capacity post"),
        )
        self.assertIn('"${capacity_helper}"', script)
        self.assertIn('"${longhorn_capacity_helper}"', script)
        self.assertIn("run-absence", script)
        self.assertIn("cleanup_absence_proven", CONTRACT.read_text(encoding="utf-8"))

    def test_three_replica_health_requires_all_management_nodes(self) -> None:
        module = load_contract()
        identity = {
            "volume_handle": "volume-handle",
            "volume_uid": "volume-uid",
        }
        result = module.validate_health(
            identity,
            {"items": [volume()]},
            {"items": replicas()},
        )
        self.assertEqual(result["healthy_replicas"], 3)
        self.assertTrue(result["replicas_on_distinct_nodes"])

        invalid = replicas()
        invalid[2]["spec"]["nodeID"] = "verda-mgmt-server-02"
        with self.assertRaisesRegex(module.ContractError, "spread"):
            module.validate_health(identity, {"items": [volume()]}, {"items": invalid})

    def test_identity_and_reschedule_proof_reject_same_node(self) -> None:
        module = load_contract()
        identity = module.capture_identity(
            pvc(),
            pvs(),
            {"items": [volume()]},
            pod("writer", "verda-mgmt-server-01"),
            RUN_ID,
            NAMESPACE,
        )
        result = module.verify_reschedule(
            identity,
            pvc(),
            pvs(),
            {"items": [volume()]},
            pod("reader", "verda-mgmt-server-02"),
        )
        self.assertTrue(result["volume_identity_preserved"])
        self.assertTrue(result["rescheduled_to_different_node"])
        with self.assertRaisesRegex(module.ContractError, "different"):
            module.verify_reschedule(
                identity,
                pvc(),
                pvs(),
                {"items": [volume()]},
                pod("reader", "verda-mgmt-server-01"),
            )

    def test_cleanup_refuses_wrong_owner_and_proves_storage_absence(self) -> None:
        module = load_contract()
        namespace = {
            "metadata": {
                "name": NAMESPACE,
                "labels": {
                    "platform.verda-demo.io/test": "longhorn-reschedule",
                    "platform.verda-demo.io/run-id": RUN_ID,
                },
            }
        }
        self.assertTrue(
            module.validate_namespace(namespace, RUN_ID, NAMESPACE)[
                "cleanup_ownership_validated"
            ]
        )
        namespace["metadata"]["labels"]["platform.verda-demo.io/run-id"] = "wrong"
        with self.assertRaisesRegex(module.ContractError, "ownership"):
            module.validate_namespace(namespace, RUN_ID, NAMESPACE)

        identity = {
            "pv_name": "pv-name",
            "pv_uid": "pv-uid",
            "volume_handle": "volume-handle",
            "volume_uid": "volume-uid",
        }
        absence = module.validate_absence(
            identity, NAMESPACE, {"items": []}, {"items": []}, {"items": []}
        )
        self.assertTrue(absence["cleanup_absence_proven"])
        with self.assertRaisesRegex(module.ContractError, "PV remains"):
            module.validate_absence(
                identity, NAMESPACE, {"items": []}, pvs(), {"items": []}
            )

    def test_cleanup_target_guards_exact_retain_to_delete_boundary(self) -> None:
        module = load_contract()
        namespace = {
            "metadata": {
                "name": NAMESPACE,
                "labels": {
                    "platform.verda-demo.io/test": "longhorn-reschedule",
                    "platform.verda-demo.io/run-id": RUN_ID,
                },
            }
        }
        identity = module.capture_identity(
            pvc(),
            pvs(),
            {"items": [volume()]},
            pod("writer", "verda-mgmt-server-01"),
            RUN_ID,
            NAMESPACE,
        )
        result = module.validate_cleanup_target(
            identity,
            namespace,
            pvc(),
            pvs(),
            {"items": [volume()]},
            RUN_ID,
            NAMESPACE,
            "Retain",
        )
        self.assertTrue(result["cleanup_target_validated"])

        patched = pvs()
        patched["items"][0]["spec"]["persistentVolumeReclaimPolicy"] = "Delete"
        result = module.validate_cleanup_target(
            identity,
            namespace,
            pvc(),
            patched,
            {"items": [volume()]},
            RUN_ID,
            NAMESPACE,
            "Delete",
        )
        self.assertEqual(result["cleanup_reclaim_policy"], "Delete")

        foreign = pvs()
        foreign["items"][0]["spec"]["claimRef"]["uid"] = "foreign-pvc"
        with self.assertRaisesRegex(module.ContractError, "ownership"):
            module.validate_cleanup_target(
                identity,
                namespace,
                pvc(),
                foreign,
                {"items": [volume()]},
                RUN_ID,
                NAMESPACE,
                "Retain",
            )

    def test_storage_class_is_exactly_three_replica_longhorn(self) -> None:
        module = load_contract()
        storage_class = {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {"name": "longhorn-critical"},
            "provisioner": "driver.longhorn.io",
            "parameters": {"numberOfReplicas": "3"},
            "reclaimPolicy": "Retain",
            "volumeBindingMode": "WaitForFirstConsumer",
            "allowVolumeExpansion": True,
        }
        self.assertEqual(
            module.validate_storage_class(storage_class)["storage_class_replicas"], 3
        )
        storage_class["parameters"]["numberOfReplicas"] = "2"
        with self.assertRaisesRegex(module.ContractError, "three replicas"):
            module.validate_storage_class(storage_class)

    def test_final_report_contains_only_sanitized_scalars(self) -> None:
        capacity = {
            "scheduled_active_pods": 42,
            "requested_cpu_cores": 2.5,
            "requested_memory_gib": 4.0,
            "one_node_loss_cpu_headroom_cores": 5.5,
            "one_node_loss_memory_headroom_gib": 12.0,
        }
        longhorn_capacity = {
            "longhorn_schedulable_node_count": 3,
            "longhorn_dedicated_disk_count": 3,
            "total_storage_available_bytes": 250_000_000_000,
            "total_storage_scheduled_bytes": 10_000_000_000,
            "worst_case_two_node_available_bytes": 160_000_000_000,
        }
        health = {
            "healthy_replicas": 3,
            "replicas_on_distinct_nodes": True,
            "volume_attached": True,
            "volume_healthy": True,
        }
        reschedule = {
            "checksum_verified_after_reschedule": True,
            "pvc_identity_preserved": True,
            "pv_identity_preserved": True,
            "rescheduled_to_different_node": True,
            "volume_identity_preserved": True,
        }
        absence = {
            "cleanup_absence_proven": True,
            "longhorn_test_data_removed_only_at_cleanup": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(name: str, document: dict) -> Path:
                path = root / f"{name}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                return path

            paths = {
                "capacity-pre": write("capacity-pre", capacity),
                "capacity-post": write("capacity-post", capacity),
                "longhorn-capacity-pre": write(
                    "longhorn-capacity-pre", longhorn_capacity
                ),
                "longhorn-capacity-post": write(
                    "longhorn-capacity-post", longhorn_capacity
                ),
                "health-before": write("health-before", health),
                "health-after": write("health-after", health),
                "reschedule": write("reschedule", reschedule),
                "absence": write("absence", absence),
            }
            command = [sys.executable, str(CONTRACT), "report"]
            for name, path in paths.items():
                command.extend((f"--{name}", str(path)))
            command.extend(("--run-id", RUN_ID))
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(
                all(not isinstance(value, (dict, list)) for value in report.values())
            )
            self.assertNotIn(RUN_ID, result.stdout)
            self.assertNotIn(NAMESPACE, result.stdout)
            self.assertNotIn("volume-handle", result.stdout)

    def test_shell_is_syntax_valid(self) -> None:
        subprocess.run(
            ["bash", "-n", SCRIPT.relative_to(ROOT).as_posix()], cwd=ROOT, check=True
        )


if __name__ == "__main__":
    unittest.main()
