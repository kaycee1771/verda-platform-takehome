#!/usr/bin/env python3
"""Offline contract tests for the Phase 5 Longhorn desired state."""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
LONGHORN = ROOT / "platform" / "management" / "longhorn"
PREREQUISITES = LONGHORN / "prerequisites"
RESOURCES = LONGHORN / "resources"
CAPACITY_GATE = ROOT / "scripts" / "phase5" / "longhorn-capacity.py"
EXPECTED_NODES = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]
MOUNT_SIZE = 103_000_000_000


def yaml_documents(path: pathlib.Path) -> list[dict]:
    return [document for document in yaml.safe_load_all(path.read_text()) if document]


def mount_report() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-19T00:00:00Z",
        "raw_uuid_recorded": False,
        "nodes": [
            {
                "node": node,
                "mount": "/var/lib/longhorn",
                "filesystem": "ext4",
                "fstab_source": "UUID",
                "uuid_sha256": str(index) * 64,
                "size_bytes": MOUNT_SIZE,
                "available_bytes": 97_000_000_000,
                "owner": "root:root",
                "mode": "0750",
                "status": "PASS",
            }
            for index, node in enumerate(EXPECTED_NODES, start=1)
        ],
    }


def longhorn_node_list() -> dict:
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "longhorn.io/v1beta2",
                "kind": "Node",
                "metadata": {"name": node, "namespace": "longhorn-system"},
                "spec": {
                    "allowScheduling": True,
                    "evictionRequested": False,
                    "tags": ["management-storage"],
                    "disks": {
                        "verda-data": {
                            "allowScheduling": True,
                            "diskDriver": "",
                            "diskType": "filesystem",
                            "evictionRequested": False,
                            "path": "/var/lib/longhorn",
                            "storageReserved": 10 * 1024**3,
                            "tags": ["dedicated"],
                        }
                    },
                },
                "status": {
                    "conditions": [
                        {"type": "Ready", "status": "True"},
                        {"type": "Schedulable", "status": "True"},
                    ],
                    "diskStatus": {
                        f"disk-{index}": {
                            "conditions": [
                                {"type": "Ready", "status": "True"},
                                {"type": "Schedulable", "status": "True"},
                            ],
                            "diskName": "verda-data",
                            "diskPath": "/var/lib/longhorn",
                            "diskType": "filesystem",
                            "filesystemType": "ext4",
                            "diskUUID": f"not-emitted-{index}",
                            "storageMaximum": MOUNT_SIZE,
                            "storageAvailable": 80_000_000_000,
                            "storageScheduled": 10_000_000_000,
                        }
                    },
                },
            }
            for index, node in enumerate(EXPECTED_NODES, start=1)
        ],
    }


class Phase5LonghornContractTests(unittest.TestCase):
    def test_chart_values_are_pinned_fail_closed_and_internal_only(self) -> None:
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text())
        self.assertEqual(lock["helm_charts"]["longhorn"]["version"], "1.12.1")
        self.assertEqual(lock["helm_charts"]["longhorn"]["app_version"], "v1.12.1")

        values = yaml.safe_load((LONGHORN / "values.yaml").read_text())
        for family in ("longhorn", "csi"):
            for name, image in values["image"][family].items():
                with self.subTest(image=f"{family}.{name}"):
                    self.assertRegex(image["tag"], r"^[^@]+@sha256:[0-9a-f]{64}$")
        self.assertEqual(values["namespaceOverride"], "longhorn-system")
        self.assertEqual(values["global"]["nodeSelector"], {"kubernetes.io/os": "linux"})
        self.assertEqual(values["service"]["ui"]["type"], "ClusterIP")
        self.assertEqual(values["service"]["manager"]["type"], "ClusterIP")
        self.assertFalse(values["ingress"]["enabled"])
        self.assertFalse(values["httproute"]["enabled"])
        self.assertFalse(values["persistence"]["createStorageClass"])
        self.assertFalse(values["persistence"]["defaultClass"])
        self.assertFalse(values["preUpgradeChecker"]["jobEnabled"])
        self.assertTrue(values["networkPolicies"]["restrictInternalTraffic"])
        self.assertTrue(values["networkPolicies"]["enabled"])
        self.assertEqual(values["networkPolicies"]["type"], "rke2")
        self.assertFalse(values["metrics"]["serviceMonitor"]["enabled"])

        settings = values["defaultSettings"]
        self.assertTrue(settings["createDefaultDiskLabeledNodes"])
        self.assertEqual(settings["defaultDataPath"], "/var/lib/longhorn")
        self.assertEqual(settings["defaultReplicaCount"], '{"v1":"3","v2":"3"}')
        self.assertFalse(settings["replicaSoftAntiAffinity"])
        self.assertTrue(settings["replicaZoneSoftAntiAffinity"])
        self.assertFalse(settings["replicaDiskSoftAntiAffinity"])
        self.assertEqual(settings["replicaAutoBalance"], "least-effort")
        self.assertEqual(settings["storageOverProvisioningPercentage"], 100)
        self.assertEqual(settings["storageMinimalAvailablePercentage"], 25)
        self.assertFalse(settings["allowEmptyNodeSelectorVolume"])
        self.assertFalse(settings["allowEmptyDiskSelectorVolume"])
        self.assertFalse(settings["allowVolumeCreationWithDegradedAvailability"])
        self.assertFalse(settings["autoSalvage"])
        self.assertEqual(settings["concurrentReplicaRebuildPerNodeLimit"], 1)
        self.assertTrue(settings["v1DataEngine"])
        self.assertFalse(settings["v2DataEngine"])
        self.assertFalse(settings["upgradeChecker"])
        self.assertFalse(settings["allowCollectingLonghornUsageMetrics"])
        self.assertEqual(
            values["longhornManager"]["updateStrategy"]["rollingUpdate"]["maxUnavailable"],
            1,
        )

    def test_prerequisites_own_namespace_and_ui_security(self) -> None:
        kustomization = yaml.safe_load((PREREQUISITES / "kustomization.yaml").read_text())
        self.assertEqual(
            kustomization["resources"],
            ["namespace.yaml", "ui-network-policy.yaml"],
        )
        namespace = yaml.safe_load((PREREQUISITES / "namespace.yaml").read_text())
        self.assertEqual(namespace["metadata"]["name"], "longhorn-system")
        labels = namespace["metadata"]["labels"]
        self.assertEqual(
            namespace["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
            "Prune=confirm,Delete=confirm",
        )
        for mode in ("enforce", "audit", "warn"):
            self.assertEqual(labels[f"pod-security.kubernetes.io/{mode}"], "privileged")
            self.assertEqual(labels[f"pod-security.kubernetes.io/{mode}-version"], "v1.35")

        policy = yaml.safe_load((PREREQUISITES / "ui-network-policy.yaml").read_text())
        self.assertEqual(policy["kind"], "NetworkPolicy")
        self.assertEqual(policy["metadata"]["namespace"], "longhorn-system")
        self.assertEqual(
            policy["spec"]["podSelector"]["matchLabels"], {"app": "longhorn-ui"}
        )
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
        self.assertEqual(policy["spec"]["ingress"], [])

    def test_resources_application_only_owns_nodes_and_storage_classes(self) -> None:
        kustomization = yaml.safe_load((RESOURCES / "kustomization.yaml").read_text())
        self.assertEqual(kustomization["resources"], ["nodes.yaml", "storageclasses.yaml"])
        self.assertFalse((RESOURCES / "namespace.yaml").exists())
        self.assertFalse((RESOURCES / "ui-network-policy.yaml").exists())

    def test_longhorn_nodes_own_only_the_three_dedicated_mounts(self) -> None:
        nodes = yaml_documents(RESOURCES / "nodes.yaml")
        self.assertEqual(len(nodes), 3)
        self.assertEqual(sorted(node["metadata"]["name"] for node in nodes), EXPECTED_NODES)
        for node in nodes:
            self.assertEqual(node["apiVersion"], "longhorn.io/v1beta2")
            self.assertEqual(node["kind"], "Node")
            self.assertEqual(node["metadata"]["namespace"], "longhorn-system")
            self.assertEqual(
                node["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                "Prune=confirm,Delete=confirm",
            )
            self.assertEqual(node["metadata"]["name"], node["spec"]["name"])
            self.assertTrue(node["spec"]["allowScheduling"])
            self.assertFalse(node["spec"]["evictionRequested"])
            self.assertEqual(node["spec"]["tags"], ["management-storage"])
            self.assertEqual(set(node["spec"]["disks"]), {"verda-data"})
            disk = node["spec"]["disks"]["verda-data"]
            self.assertEqual(disk["path"], "/var/lib/longhorn")
            self.assertEqual(disk["diskType"], "filesystem")
            self.assertEqual(disk["diskDriver"], "")
            self.assertEqual(disk["storageReserved"], 10 * 1024**3)
            self.assertEqual(disk["tags"], ["dedicated"])

    def test_storage_classes_make_critical_the_only_default(self) -> None:
        classes = yaml_documents(RESOURCES / "storageclasses.yaml")
        self.assertEqual({item["metadata"]["name"] for item in classes}, {
            "longhorn-critical",
            "longhorn-standard",
        })
        by_name = {item["metadata"]["name"]: item for item in classes}
        critical = by_name["longhorn-critical"]
        standard = by_name["longhorn-standard"]
        self.assertEqual(
            critical["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"],
            "true",
        )
        self.assertEqual(
            standard["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"],
            "false",
        )
        self.assertEqual(critical["parameters"]["numberOfReplicas"], "3")
        self.assertEqual(standard["parameters"]["numberOfReplicas"], "2")
        self.assertEqual(critical["reclaimPolicy"], "Retain")
        self.assertEqual(standard["reclaimPolicy"], "Delete")
        for storage_class in classes:
            self.assertEqual(storage_class["provisioner"], "driver.longhorn.io")
            self.assertTrue(storage_class["allowVolumeExpansion"])
            self.assertEqual(storage_class["volumeBindingMode"], "WaitForFirstConsumer")
            parameters = storage_class["parameters"]
            self.assertEqual(parameters["diskSelector"], "dedicated")
            self.assertEqual(parameters["nodeSelector"], "management-storage")
            self.assertEqual(parameters["dataEngine"], "v1")
            self.assertEqual(parameters["dataLocality"], "disabled")
            self.assertEqual(parameters["replicaAutoBalance"], "least-effort")
            self.assertEqual(parameters["replicaSoftAntiAffinity"], "disabled")
            self.assertEqual(parameters["replicaZoneSoftAntiAffinity"], "enabled")
            self.assertEqual(parameters["replicaDiskSoftAntiAffinity"], "disabled")
            self.assertTrue(all(isinstance(value, str) for value in parameters.values()))

    def test_owned_desired_state_contains_no_credentials_or_external_endpoint(self) -> None:
        text = "\n".join(path.read_text() for path in LONGHORN.rglob("*.yaml"))
        for forbidden in (
            "kind: Secret",
            "accessKey",
            "secretKey",
            "credentialSecret",
            "backupTarget:",
            "objects.fin-03",
            "NodePort",
            "LoadBalancer",
        ):
            self.assertNotIn(forbidden, text)

    def run_capacity_gate(
        self, mount: dict, nodes: dict | None = None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            mount_path = root / "mount.json"
            mount_path.write_text(json.dumps(mount), encoding="utf-8")
            command = [sys.executable, str(CAPACITY_GATE), "--mount-report", str(mount_path)]
            if nodes is not None:
                nodes_path = root / "nodes.json"
                nodes_path.write_text(json.dumps(nodes), encoding="utf-8")
                command.extend(("--longhorn-nodes", str(nodes_path)))
            return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_capacity_gate_accepts_sanitized_pre_and_post_install_captures(self) -> None:
        pre = self.run_capacity_gate(mount_report())
        self.assertEqual(pre.returncode, 0, pre.stderr)
        pre_summary = json.loads(pre.stdout)
        self.assertEqual(pre_summary["mode"], "pre-install")
        self.assertEqual(pre_summary["dedicated_mount_count"], 3)

        post = self.run_capacity_gate(mount_report(), longhorn_node_list())
        self.assertEqual(post.returncode, 0, post.stderr)
        post_summary = json.loads(post.stdout)
        self.assertEqual(post_summary["mode"], "post-install")
        self.assertEqual(post_summary["longhorn_schedulable_node_count"], 3)
        self.assertEqual(post_summary["longhorn_dedicated_disk_count"], 3)
        self.assertEqual(post_summary["critical_class_replicas_after_one_node_loss"], 2)
        self.assertGreater(post_summary["worst_case_two_node_available_bytes"], 0)
        self.assertNotIn("verda-mgmt", post.stdout)
        self.assertNotIn("not-emitted", post.stdout)

    def test_capacity_gate_rejects_root_fallback_extra_disk_and_low_headroom(self) -> None:
        root_fallback = mount_report()
        root_fallback["nodes"][0]["mount"] = "/"
        self.assertNotEqual(self.run_capacity_gate(root_fallback).returncode, 0)

        extra_disk = longhorn_node_list()
        extra_disk["items"][0]["spec"]["disks"]["root"] = copy.deepcopy(
            extra_disk["items"][0]["spec"]["disks"]["verda-data"]
        )
        extra_disk["items"][0]["spec"]["disks"]["root"]["path"] = "/"
        self.assertNotEqual(self.run_capacity_gate(mount_report(), extra_disk).returncode, 0)

        low_headroom = longhorn_node_list()
        observed = next(iter(low_headroom["items"][0]["status"]["diskStatus"].values()))
        observed["storageAvailable"] = 10_000_000_000
        self.assertNotEqual(self.run_capacity_gate(mount_report(), low_headroom).returncode, 0)

        wrong_item_api = longhorn_node_list()
        wrong_item_api["items"][0]["apiVersion"] = "longhorn.io/v1beta1"
        self.assertNotEqual(
            self.run_capacity_gate(mount_report(), wrong_item_api).returncode,
            0,
        )

    def test_capacity_gate_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mount_path = pathlib.Path(directory) / "mount.json"
            mount_path.write_text(
                '{"schema_version":1,"schema_version":1,"nodes":[]}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(CAPACITY_GATE), "--mount-report", str(mount_path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate object key", result.stderr)


if __name__ == "__main__":
    unittest.main()
