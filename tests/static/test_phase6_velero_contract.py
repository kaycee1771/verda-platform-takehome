from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "versions.lock.yaml"
VELERO = ROOT / "platform" / "management" / "velero"
VALUES = VELERO / "values.yaml"
ACTIVATION = VELERO / "activation-contract.yaml"
CAPACITY = VELERO / "capacity-input.yaml"
RESOURCES = VELERO / "resources"
CHART = ROOT / ".local" / "chart-cache" / "velero-12.1.0.tgz"

EXPECTED_IMAGES = {
    "docker.io/velero/velero@sha256:11459094b1b21ec7c817b08f8067d9e89380835547915cac9c4132ff05b55b90",
    "docker.io/velero/velero-plugin-for-aws@sha256:7e82f717f44e89671212e0dfce7e061321c386ea84a33bca64a671670ca6c278",
}


class RenderLoader(yaml.SafeLoader):
    """Load chart CRDs whose OpenAPI enums contain the YAML `=` token."""


RenderLoader.add_constructor(
    "tag:yaml.org,2002:value",
    lambda loader, node: loader.construct_scalar(node),
)


def load_one(path: Path) -> dict:
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise AssertionError(f"{path} must contain exactly one mapping")
    return documents[0]


def find_helm() -> str:
    helm = shutil.which("helm")
    if helm:
        return helm
    bundled = Path("/opt/aqua/bin/helm")
    if bundled.is_file():
        return str(bundled)
    raise unittest.SkipTest("pinned Helm is unavailable; run in the quality container")


def render_chart() -> list[dict]:
    if not CHART.is_file():
        raise unittest.SkipTest("offline Velero chart cache is absent; run make bootstrap-tools")
    result = subprocess.run(
        [
            find_helm(),
            "template",
            "velero",
            str(CHART),
            "--namespace",
            "velero",
            "--include-crds",
            "--kube-version",
            "1.35.7",
            "--api-versions",
            "monitoring.coreos.com/v1",
            "--values",
            str(VALUES),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return [
        item
        for item in yaml.load_all(result.stdout, Loader=RenderLoader)
        if isinstance(item, dict)
    ]


def objects_of_kind(documents: list[dict], kind: str) -> list[dict]:
    return [document for document in documents if document.get("kind") == kind]


def assert_activation_allowed(contract: dict) -> None:
    if contract.get("activation_status") != "ready":
        raise ValueError("Velero activation is not ready")
    gates = contract.get("blocking_gates")
    if not isinstance(gates, dict) or not all(gates.values()):
        raise ValueError("Velero activation gates are incomplete")
    for image in contract.get("required_images", []):
        digest = image.get("digest") if isinstance(image, dict) else None
        if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
            raise ValueError("Velero image digest is unresolved")


class Phase6VeleroContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = load_one(LOCK)
        cls.values = load_one(VALUES)
        cls.activation = load_one(ACTIVATION)
        cls.capacity = load_one(CAPACITY)
        cls.documents = render_chart()
        cls.bsl = load_one(RESOURCES / "backup-storage-location.yaml")
        cls.schedule = load_one(RESOURCES / "management-environments-schedule.yaml")

    def test_chart_provenance_and_activation_fail_closed(self) -> None:
        chart = self.lock["helm_charts"]["velero"]
        self.assertEqual(chart["version"], "12.1.0")
        self.assertEqual(chart["app_version"], "1.18.1")
        self.assertEqual(chart["archive_sha256"], self.activation["chart"]["archive_sha256"])
        self.assertEqual(
            hashlib.sha256(CHART.read_bytes()).hexdigest(),
            chart["archive_sha256"],
        )
        self.assertIn("pending", chart["selection_status"])
        self.assertEqual(self.activation["activation_status"], "blocked")
        gates = self.activation["blocking_gates"]
        self.assertTrue(gates["immutable_image_digests_locked"])
        self.assertTrue(gates["immutable_image_provenance_recorded"])
        self.assertIn(False, gates.values())
        with self.assertRaisesRegex(ValueError, "not ready"):
            assert_activation_allowed(self.activation)

    def test_exact_image_inventory_is_digest_locked_and_no_transitive_job_runs(self) -> None:
        images: set[str] = set()
        for kind in ("Deployment", "DaemonSet", "Job"):
            for workload in objects_of_kind(self.documents, kind):
                pod_spec = workload["spec"]["template"]["spec"]
                images.update(
                    container["image"]
                    for container in pod_spec.get("initContainers", []) + pod_spec["containers"]
                )
        self.assertEqual(images, EXPECTED_IMAGES)
        self.assertEqual(objects_of_kind(self.documents, "Job"), [])
        self.assertFalse(self.values["upgradeCRDs"])
        self.assertFalse(self.values["cleanUpCRDs"])
        self.assertRegex(self.values["image"]["digest"], r"^sha256:[0-9a-f]{64}$")
        locked = {
            f"{item['repository']}@{item['digest']}"
            for item in self.activation["required_images"]
        }
        self.assertEqual(locked, EXPECTED_IMAGES)
        self.assertTrue(
            all(
                item["digest_provenance"] == "docker-hub-tag-api-2026-08-20"
                for item in self.activation["required_images"]
            )
        )
        chart_images = self.lock["helm_charts"]["velero"]["images"]
        self.assertEqual(
            {f"{item['reference']}@{item['digest']}" for item in chart_images.values()},
            {
                "docker.io/velero/velero:v1.18.1@sha256:11459094b1b21ec7c817b08f8067d9e89380835547915cac9c4132ff05b55b90",
                "docker.io/velero/velero-plugin-for-aws:v1.14.0@sha256:7e82f717f44e89671212e0dfce7e061321c386ea84a33bca64a671670ca6c278",
            },
        )

    def test_every_rendered_container_and_init_container_has_exact_resources(self) -> None:
        workloads = objects_of_kind(self.documents, "Deployment") + objects_of_kind(
            self.documents, "DaemonSet"
        )
        self.assertEqual(len(workloads), 2)
        for workload in workloads:
            pod_spec = workload["spec"]["template"]["spec"]
            containers = pod_spec.get("initContainers", []) + pod_spec["containers"]
            for container in containers:
                with self.subTest(workload=workload["metadata"]["name"], container=container["name"]):
                    resources = container.get("resources", {})
                    self.assertEqual(set(resources.get("requests", {})), {"cpu", "memory"})
                    self.assertEqual(set(resources.get("limits", {})), {"cpu", "memory"})
                    security = container.get("securityContext", {})
                    self.assertFalse(security["allowPrivilegeEscalation"])
                    self.assertFalse(security["privileged"])
                    self.assertTrue(security["readOnlyRootFilesystem"])
                    self.assertEqual(security["capabilities"]["drop"], ["ALL"])
                    self.assertEqual(
                        security["seccompProfile"], {"type": "RuntimeDefault"}
                    )

    def test_existing_secret_is_the_only_credential_boundary(self) -> None:
        credentials = self.values["credentials"]
        self.assertTrue(credentials["useSecret"])
        self.assertEqual(credentials["existingSecret"], "velero-management-s3")
        self.assertEqual(credentials["secretContents"], {})
        self.assertEqual(objects_of_kind(self.documents, "Secret"), [])
        self.assertEqual(
            self.bsl["spec"]["credential"],
            {"name": "velero-management-s3", "key": "cloud"},
        )

    def test_backup_rbac_is_read_only_and_not_cluster_admin(self) -> None:
        self.assertFalse(self.values["rbac"]["clusterAdministrator"])
        bindings = objects_of_kind(self.documents, "ClusterRoleBinding")
        self.assertTrue(bindings)
        self.assertTrue(all(item["roleRef"]["name"] != "cluster-admin" for item in bindings))
        reader = next(
            item
            for item in objects_of_kind(self.documents, "ClusterRole")
            if item["metadata"]["name"] == "velero-namespaced-backup-reader"
        )
        self.assertEqual(len(reader["rules"]), 1)
        self.assertEqual(set(reader["rules"][0]["verbs"]), {"get", "list", "watch"})
        self.assertEqual(
            [
                item
                for item in objects_of_kind(self.documents, "RoleBinding")
                if item["metadata"]["name"] == "velero-backup-reader"
            ],
            [],
        )
        self.assertFalse(
            self.activation["blocking_gates"]["namespace_backup_reader_bindings_proven"]
        )

    def test_location_and_schedule_are_post_crd_and_fsb_only(self) -> None:
        kustomization = load_one(RESOURCES / "kustomization.yaml")
        self.assertEqual(
            set(kustomization["resources"]),
            {"backup-storage-location.yaml", "management-environments-schedule.yaml"},
        )
        self.assertEqual(self.bsl["kind"], "BackupStorageLocation")
        self.assertEqual(self.schedule["kind"], "Schedule")
        self.assertEqual(self.bsl["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-3")
        self.assertEqual(
            self.schedule["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-3"
        )
        self.assertFalse(self.values["backupsEnabled"])
        self.assertFalse(self.values["snapshotsEnabled"])
        self.assertEqual(objects_of_kind(self.documents, "BackupStorageLocation"), [])
        self.assertEqual(objects_of_kind(self.documents, "VolumeSnapshotLocation"), [])
        self.assertEqual(objects_of_kind(self.documents, "Schedule"), [])
        self.assertEqual(self.activation["volume_strategy"]["type"], "filesystem-backup")
        self.assertFalse(
            self.activation["volume_strategy"]["volume_snapshot_location_created"]
        )

        storage = self.bsl["spec"]
        self.assertEqual(storage["provider"], "aws")
        self.assertEqual(storage["objectStorage"], {"bucket": "verda-takehome-velero", "prefix": "mgmt"})
        self.assertEqual(storage["config"]["region"], "us-east-1")
        self.assertEqual(storage["config"]["s3Url"], "https://objects.fin-03.verda.storage")
        self.assertEqual(storage["config"]["s3ForcePathStyle"], "true")
        self.assertEqual(storage["config"]["checksumAlgorithm"], "")

        template = self.schedule["spec"]["template"]
        self.assertTrue(self.schedule["spec"]["paused"])
        self.assertFalse(self.activation["blocking_gates"]["schedule_unpaused"])
        self.assertEqual(
            set(template["includedNamespaces"]),
            {"demo-dev", "demo-staging", "demo-prod"},
        )
        self.assertFalse(template["includeClusterResources"])
        self.assertFalse(template["snapshotVolumes"])
        self.assertTrue(template["defaultVolumesToFsBackup"])
        self.assertEqual(template["storageLocation"], "management-s3")
        self.assertEqual(template["ttl"], "168h")

    def test_metrics_and_dynamic_workloads_are_bounded(self) -> None:
        service_monitors = objects_of_kind(self.documents, "ServiceMonitor")
        pod_monitors = objects_of_kind(self.documents, "PodMonitor")
        self.assertEqual(len(service_monitors), 1)
        self.assertEqual(len(pod_monitors), 1)
        for monitor in service_monitors + pod_monitors:
            self.assertEqual(
                monitor["metadata"]["labels"]["platform.verda-demo.io/monitor"],
                "true",
            )
        self.assertEqual(len(objects_of_kind(self.documents, "PrometheusRule")), 1)
        node_config = json.loads(
            self.values["configMaps"]["node-agent-config"]["data"]["node-agent.json"]
        )
        self.assertEqual(node_config["loadConcurrency"], {"globalConfig": 1, "prepareQueueLength": 3})
        self.assertEqual(node_config["podResources"]["cpuRequest"], "250m")
        self.assertEqual(node_config["podResources"]["cpuLimit"], "750m")
        self.assertEqual(node_config["priorityClassName"], "platform-workload")
        priority_classes = {
            item["metadata"]["name"]
            for item in yaml.safe_load_all(
                (
                    ROOT
                    / "platform"
                    / "management"
                    / "namespaces"
                    / "priorityclasses.yaml"
                ).read_text(encoding="utf-8")
            )
            if isinstance(item, dict) and item.get("kind") == "PriorityClass"
        }
        self.assertIn("platform-workload", priority_classes)
        self.assertIn("platform-important", priority_classes)
        self.assertIn(
            "--node-agent-configmap=velero-node-agent-config",
            self.values["nodeAgent"]["extraArgs"],
        )
        repository = self.values["configuration"]["repositoryMaintenanceJob"]
        maintenance = repository["repositoryConfigData"]["global"]["podResources"]
        self.assertEqual(
            repository["repositoryConfigData"]["global"]["priorityClassName"],
            "platform-workload",
        )
        self.assertEqual(maintenance["cpuRequest"], "50m")
        self.assertEqual(maintenance["memoryLimit"], "256Mi")

    def test_capacity_model_matches_values_and_generated_peak(self) -> None:
        controller = self.capacity["workloads"]["controller"]
        node_agent = self.capacity["workloads"]["node-agent"]
        self.assertEqual(
            self.capacity["workloads"]["data-mover"]["priority_class"],
            "platform-workload",
        )
        self.assertEqual(
            self.capacity["workloads"]["repository-maintenance"]["priority_class"],
            "platform-workload",
        )
        self.assertEqual(controller["requests"], self.values["resources"]["requests"])
        self.assertEqual(node_agent["requests_per_pod"], self.values["nodeAgent"]["resources"]["requests"])
        self.assertEqual(self.capacity["steady_state"], {"cpu": "500m", "memory": "1024Mi"})
        self.assertEqual(
            self.capacity["backup_peak_including_data_movers_and_maintenance"],
            {"cpu": "1300m", "memory": "1920Mi"},
        )
        self.assertEqual(self.capacity["persistent_volume_claims"], [])

    def test_owned_files_have_no_secret_object_or_literal_credential(self) -> None:
        forbidden_literals = ("aws_access_key_id=", "aws_secret_access_key=", "AKIA")
        for path in VELERO.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^kind:\s*Secret\s*$", path)
            for literal in forbidden_literals:
                self.assertNotIn(literal, text, path)
        readme = (VELERO / "README.md").read_text(encoding="utf-8")
        normalized = " ".join(readme.split())
        self.assertIn("not a restore-completeness claim", normalized)
        self.assertIn("Neither proves application consistency", normalized)


if __name__ == "__main__":
    unittest.main()
