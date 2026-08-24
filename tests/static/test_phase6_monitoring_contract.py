from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "platform" / "management" / "monitoring"
VALUES = MONITORING / "values.yaml"
IMAGE_LOCK = MONITORING / "image-lock.yaml"
CAPACITY_PROJECTION = MONITORING / "capacity" / "operator-workloads.capacity-input"
CHART = ROOT / ".local" / "chart-cache" / "kube-prometheus-stack-88.3.0.tgz"
CAPACITY_SCRIPT = ROOT / "scripts" / "phase6" / "capacity-admission.py"
GIB = 1024**3
MIB = 1024**2

EXPECTED_IMAGES = {
    "docker.io/grafana/grafana:13.1.3": "sha256:ab5cb380e3ff3172d6c8bd2e7cfd31cce977d2881b260e1f5bc089bf0b759b43",
    "quay.io/kiwigrid/k8s-sidecar:2.10.1": "sha256:7eac5c4fed714a18d038fc9fea57d8744d113367935dac0ea4eb6a87cef704a3",
    "quay.io/prometheus-operator/prometheus-config-reloader:v0.93.0": "sha256:0ccb22ca9f3f6fd9f76ce95585d18bd2e363d421c534dde710be4bd13caa551d",
    "quay.io/prometheus-operator/prometheus-operator:v0.93.0": "sha256:a001ed10a3823bbf2410ea347796d0e35ff8decd24fb98acbe7ab9e98d431c39",
    "quay.io/prometheus/alertmanager:v0.33.1": "sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d",
    "quay.io/prometheus/node-exporter:v1.12.1-distroless": "sha256:8c9bac11973b94b59be88d6e11fee4429aa743c8846cdc75d65b18db33f6a106",
    "quay.io/prometheus/prometheus:v3.13.2-distroless": "sha256:64f71bb84e03c855948418b0fc5dea53e9543d8e3fc9931598f583805507f05e",
    "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.19.1": "sha256:85108987d044b18a098126732f98602df408888c0f7d456241f5abefb9744bc1",
    "quay.io/thanos/thanos:v0.42.4": "sha256:b567818fe608067eb0f1d7c2c4fe361e7ad83c8a256234c97685f1d0bf670cc8",
}


class RenderLoader(yaml.SafeLoader):
    """Load Helm CRDs whose OpenAPI enums contain the YAML `=` token."""


RenderLoader.add_constructor(
    "tag:yaml.org,2002:value",
    lambda loader, node: loader.construct_scalar(node),
)


def load_yaml(path: Path) -> dict:
    result = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise AssertionError(f"{path} must contain a mapping")
    return result


def assert_digest_lock_admissible(lock: dict) -> None:
    images = lock.get("images")
    if lock.get("selection_status") != "verified" or not isinstance(images, list):
        raise ValueError("monitoring image lock is not verified")
    for image in images:
        digest = image.get("digest") if isinstance(image, dict) else None
        if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("monitoring image digest is unresolved")


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
        raise unittest.SkipTest("offline chart cache is absent; run make bootstrap-tools")
    result = subprocess.run(
        [
            find_helm(),
            "template",
            "monitoring",
            str(CHART),
            "--namespace",
            "monitoring",
            "--include-crds",
            "--kube-version",
            "1.35.7",
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


def object_of_kind(documents: list[dict], kind: str) -> list[dict]:
    return [document for document in documents if document.get("kind") == kind]


class Phase6MonitoringContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.values = load_yaml(VALUES)
        cls.documents = render_chart()

    def test_chart_and_lean_storage_contract_are_exact(self) -> None:
        prometheus = self.values["prometheus"]["prometheusSpec"]
        alertmanager = self.values["alertmanager"]["alertmanagerSpec"]
        self.assertEqual(prometheus["replicas"], 1)
        self.assertEqual(prometheus["shards"], 1)
        self.assertEqual(prometheus["retention"], "3d")
        self.assertEqual(prometheus["retentionSize"], "6GB")
        self.assertEqual(
            prometheus["storageSpec"]["volumeClaimTemplate"]["spec"],
            {
                "storageClassName": "longhorn-critical",
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "10Gi"}},
            },
        )
        self.assertEqual(alertmanager["replicas"], 1)
        self.assertEqual(alertmanager["retention"], "72h")
        self.assertEqual(
            alertmanager["storage"]["volumeClaimTemplate"]["spec"],
            {
                "storageClassName": "longhorn-critical",
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "2Gi"}},
            },
        )

    def test_all_enabled_rendered_containers_have_explicit_resources(self) -> None:
        workloads = object_of_kind(self.documents, "Deployment") + object_of_kind(
            self.documents, "DaemonSet"
        )
        self.assertEqual(len(workloads), 4)
        for workload in workloads:
            pod_spec = workload["spec"]["template"]["spec"]
            containers = pod_spec.get("initContainers", []) + pod_spec["containers"]
            self.assertGreater(len(containers), 0)
            for container in containers:
                with self.subTest(workload=workload["metadata"]["name"], container=container["name"]):
                    resources = container.get("resources", {})
                    self.assertEqual(set(resources.get("requests", {})), {"cpu", "memory"})
                    self.assertEqual(set(resources.get("limits", {})), {"cpu", "memory"})

        for custom_resource in object_of_kind(self.documents, "Prometheus") + object_of_kind(
            self.documents, "Alertmanager"
        ):
            resources = custom_resource["spec"].get("resources", {})
            self.assertEqual(set(resources.get("requests", {})), {"cpu", "memory"})
            self.assertEqual(set(resources.get("limits", {})), {"cpu", "memory"})

        reloader = self.values["prometheusOperator"]["prometheusConfigReloader"]["resources"]
        self.assertEqual(set(reloader["requests"]), {"cpu", "memory"})
        self.assertEqual(set(reloader["limits"]), {"cpu", "memory"})

    def test_grafana_and_metrics_rbac_are_namespace_and_configmap_scoped(self) -> None:
        grafana = self.values["grafana"]
        self.assertEqual(
            grafana["rbac"],
            {"create": False, "namespaced": True, "namespaces": ["monitoring"]},
        )
        self.assertEqual(grafana["sidecar"]["dashboards"]["resource"], "configmap")
        self.assertEqual(grafana["sidecar"]["datasources"]["resource"], "configmap")
        self.assertTrue(grafana["containerSecurityContext"]["readOnlyRootFilesystem"])
        self.assertTrue(grafana["sidecar"]["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(self.values["kube-state-metrics"]["collectorsExclude"], ["secrets"])

        grafana_roles = [
            document
            for document in self.documents
            if document.get("kind") in {"Role", "ClusterRole"}
            and "grafana" in document.get("metadata", {}).get("name", "")
        ]
        self.assertEqual({document["kind"] for document in grafana_roles}, {"Role"})
        self.assertEqual(
            {document["metadata"]["name"] for document in grafana_roles},
            {"monitoring-grafana-sidecars"},
        )
        for document in grafana_roles:
            resources = {
                resource
                for rule in document.get("rules", [])
                for resource in rule.get("resources", [])
            }
            self.assertNotIn("secrets", resources)

        state_metrics_roles = [
            document
            for document in self.documents
            if document.get("kind") in {"Role", "ClusterRole"}
            and "kube-state-metrics" in document.get("metadata", {}).get("name", "")
        ]
        self.assertGreater(len(state_metrics_roles), 0)
        for document in state_metrics_roles:
            resources = {
                resource
                for rule in document.get("rules", [])
                for resource in rule.get("resources", [])
            }
            self.assertNotIn("secrets", resources)

    def test_operator_projection_covers_generated_workloads_and_capacity(self) -> None:
        projection = [
            item
            for item in yaml.safe_load_all(CAPACITY_PROJECTION.read_text(encoding="utf-8"))
            if isinstance(item, dict)
        ]
        self.assertEqual(len(projection), 2)
        self.assertEqual({item["kind"] for item in projection}, {"StatefulSet"})
        self.assertEqual(
            {item["metadata"]["annotations"]["capacity.platform.verda.io/projection-only"] for item in projection},
            {"true"},
        )
        resources_kustomization = load_yaml(MONITORING / "resources" / "kustomization.yaml")
        self.assertNotIn("../capacity/operator-workloads.yaml", resources_kustomization["resources"])

        spec = importlib.util.spec_from_file_location("phase6_monitoring_capacity", CAPACITY_SCRIPT)
        assert spec and spec.loader
        reducer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = reducer
        spec.loader.exec_module(reducer)
        result = reducer.component_capacity(
            projection,
            {
                "expected_document_count": 2,
                "expected_workload_count": 2,
                "expected_pvc_definition_count": 2,
            },
            3,
            {"longhorn-critical": {"replicas": 3, "replicas_after_one_node_loss": 2}},
            "kube_prometheus_stack_operator_projection",
            set(),
        )
        self.assertEqual(result.steady.request_cpu_millicores, 320)
        self.assertEqual(result.peak.request_cpu_millicores, 320)
        self.assertEqual(result.steady.request_memory_bytes, 704 * MIB)
        self.assertEqual(result.peak.request_memory_bytes, 704 * MIB)
        self.assertEqual(result.steady.limit_cpu_millicores, 1400)
        self.assertEqual(result.steady.limit_memory_bytes, 2048 * MIB)
        self.assertEqual(result.logical_pvc_bytes, 12 * GIB)
        self.assertEqual(result.raw_pvc_bytes, 36 * GIB)
        self.assertEqual(result.one_node_loss_pvc_bytes, 24 * GIB)

    def test_exact_enabled_image_inventory_is_blocked_until_digests_resolve(self) -> None:
        rendered_images: set[str] = set()
        for workload in object_of_kind(self.documents, "Deployment") + object_of_kind(
            self.documents, "DaemonSet"
        ):
            pod_spec = workload["spec"]["template"]["spec"]
            rendered_images.update(
                container["image"]
                for container in pod_spec.get("initContainers", []) + pod_spec["containers"]
            )
            for container in pod_spec["containers"]:
                for argument in container.get("args", []):
                    for prefix in (
                        "--prometheus-config-reloader=",
                        "--thanos-default-base-image=",
                    ):
                        if argument.startswith(prefix):
                            rendered_images.add(argument.removeprefix(prefix))
        for custom_resource in object_of_kind(self.documents, "Prometheus") + object_of_kind(
            self.documents, "Alertmanager"
        ):
            rendered_images.add(custom_resource["spec"]["image"])
        expected_rendered = {
            f"{reference}@{digest}" for reference, digest in EXPECTED_IMAGES.items()
        }
        self.assertEqual(rendered_images, expected_rendered)

        lock = load_yaml(IMAGE_LOCK)
        self.assertEqual(lock["chart_version"], "88.3.0")
        self.assertEqual(lock["app_version"], "v0.93.0")
        self.assertEqual({item["reference"] for item in lock["images"]}, set(EXPECTED_IMAGES))
        self.assertEqual(len(lock["images"]), len(EXPECTED_IMAGES))
        self.assertEqual(
            {item["reference"]: item["digest"] for item in lock["images"]},
            EXPECTED_IMAGES,
        )
        assert_digest_lock_admissible(lock)

    def test_stock_and_git_provisioned_observability_assets_are_retained(self) -> None:
        self.assertTrue(self.values["defaultRules"]["create"])
        self.assertTrue(self.values["grafana"]["defaultDashboardsEnabled"])
        self.assertFalse(self.values["grafana"]["defaultDashboardsEditable"])
        self.assertEqual(len(object_of_kind(self.documents, "PrometheusRule")), 30)
        stock_dashboards = [
            item
            for item in object_of_kind(self.documents, "ConfigMap")
            if item["metadata"]["name"].startswith("monitoring-kube-prometheus-")
            and item["metadata"]["name"] != "monitoring-kube-prometheus-grafana-datasource"
        ]
        self.assertEqual(len(stock_dashboards), 23)

        dashboard = load_yaml(MONITORING / "resources" / "grafana-dashboard-platform.yaml")
        datasource = load_yaml(MONITORING / "resources" / "grafana-datasource-loki.yaml")
        self.assertEqual(dashboard["metadata"]["labels"]["grafana_dashboard"], "1")
        self.assertEqual(datasource["metadata"]["labels"]["grafana_datasource"], "1")
        parsed_dashboard = json.loads(dashboard["data"]["platform-overview.json"])
        self.assertEqual(parsed_dashboard["uid"], "verda-platform")
        self.assertEqual(len(parsed_dashboard["panels"]), 4)
        parsed_datasource = yaml.safe_load(datasource["data"]["loki.yaml"])
        self.assertEqual(parsed_datasource["datasources"][0]["uid"], "loki")
        self.assertFalse(parsed_datasource["datasources"][0]["editable"])

    def test_prometheus_and_alertmanager_have_no_public_surface(self) -> None:
        self.assertEqual(object_of_kind(self.documents, "Ingress"), [])
        self.assertEqual(object_of_kind(self.documents, "HTTPRoute"), [])
        services = object_of_kind(self.documents, "Service")
        self.assertEqual(len(services), 7)
        self.assertTrue(
            all(service["spec"].get("type", "ClusterIP") == "ClusterIP" for service in services)
        )
        self.assertTrue(all(not service["spec"].get("externalIPs") for service in services))
        self.assertTrue(all("loadBalancerClass" not in service["spec"] for service in services))
        self.assertFalse(self.values["prometheus"]["ingress"]["enabled"])
        self.assertFalse(self.values["prometheus"]["ingressPerReplica"]["enabled"])
        self.assertFalse(self.values["alertmanager"]["ingress"]["enabled"])

    def test_prometheus_discovers_only_explicit_platform_monitors(self) -> None:
        self.assertEqual(
            self.values["commonLabels"]["platform.verda-demo.io/monitor"],
            "true",
        )
        prometheus = self.values["prometheus"]["prometheusSpec"]
        expected = {
            "matchLabels": {"platform.verda-demo.io/monitor": "true"}
        }
        self.assertEqual(prometheus["serviceMonitorSelector"], expected)
        self.assertEqual(prometheus["podMonitorSelector"], expected)
        self.assertEqual(prometheus["serviceMonitorNamespaceSelector"], {})
        self.assertEqual(prometheus["podMonitorNamespaceSelector"], {})
        self.assertTrue(prometheus["ignoreNamespaceSelectors"])
        self.assertFalse(self.values["alertmanager"]["ingressPerReplica"]["enabled"])

    def test_rke2_coredns_metrics_ingress_is_exact(self) -> None:
        policies = [
            item
            for item in self.values["extraManifests"]
            if item.get("kind") == "NetworkPolicy"
        ]
        self.assertEqual(len(policies), 1)
        policy = policies[0]
        self.assertEqual(policy["metadata"], {
            "name": "monitoring-coredns-prometheus-ingress",
            "namespace": "kube-system",
        })
        self.assertEqual(policy["spec"]["podSelector"], {
            "matchLabels": {"k8s-app": "kube-dns"}
        })
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
        self.assertEqual(policy["spec"]["ingress"], [{
            "from": [{
                "namespaceSelector": {"matchLabels": {
                    "kubernetes.io/metadata.name": "monitoring"
                }},
                "podSelector": {"matchLabels": {
                    "app.kubernetes.io/name": "prometheus"
                }},
            }],
            "ports": [{"protocol": "TCP", "port": 9153}],
        }])


if __name__ == "__main__":
    unittest.main()
