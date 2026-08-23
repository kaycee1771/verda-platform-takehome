from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "versions.lock.yaml"
LOKI = ROOT / "platform" / "management" / "loki"
ALLOY = ROOT / "observability" / "alloy"
LOGQL = ROOT / "observability" / "logql"


def load_one(path: Path) -> dict:
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    assert len(documents) == 1
    assert isinstance(documents[0], dict)
    return documents[0]


class Phase6LokiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.versions = load_one(LOCK)
        cls.values = load_one(LOKI / "values.yaml")
        cls.activation = load_one(LOKI / "activation-contract.yaml")
        cls.capacity = load_one(LOKI / "capacity-input.yaml")

    def test_chart_provenance_matches_lock_and_activation_waits_only_for_capacity(self) -> None:
        chart = self.versions["helm_charts"]["loki"]
        self.assertEqual(chart["version"], "7.3.0")
        self.assertEqual(chart["app_version"], "3.6.12")
        self.assertEqual(chart["archive_sha256"], self.activation["chart"]["archive_sha256"])
        self.assertIn("pending", chart["selection_status"])
        self.assertEqual(self.activation["activation_status"], "ready-for-capacity-admission")
        self.assertEqual(self.capacity["activation_status"], "ready-for-capacity-admission")
        self.assertEqual(self.activation["target_namespace"], "loki")
        self.assertFalse(self.activation["blocking_gates"]["root_application_allowed"])
        self.assertEqual(
            self.values["kubeVersionOverride"].lstrip("v"),
            self.versions["platform"]["kubernetes_version"],
        )

    def test_image_digests_are_locked_while_live_activation_stays_closed(self) -> None:
        chart_images = self.versions["helm_charts"]["loki"]["images"]
        self.assertEqual(
            self.values["loki"]["image"]["digest"], chart_images["loki"]["digest"]
        )
        self.assertEqual(
            self.values["gateway"]["image"]["digest"],
            chart_images["gateway"]["digest"],
        )
        for image in self.activation["required_images"]:
            self.assertRegex(image["digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(
                image["digest_provenance"],
                "registry-v2-manifest-response-2026-08-20",
            )
        gates = self.activation["blocking_gates"]
        self.assertTrue(gates["immutable_image_digests_locked"])
        self.assertTrue(gates["immutable_image_provenance_recorded"])
        self.assertTrue(gates["filesystem_storage_selected"])
        self.assertTrue(gates["longhorn_critical_storage_selected"])
        self.assertFalse(gates["external_credentials_required"])
        self.assertFalse(gates["capacity_admission_passed"])

    def test_single_binary_only_and_every_other_mode_is_zero(self) -> None:
        self.assertEqual(self.values["deploymentMode"], "SingleBinary")
        self.assertEqual(self.values["singleBinary"]["replicas"], 1)
        zero_groups = (
            "backend",
            "read",
            "write",
            "ingester",
            "distributor",
            "querier",
            "queryFrontend",
            "queryScheduler",
            "compactor",
            "indexGateway",
            "bloomGateway",
            "bloomPlanner",
            "bloomBuilder",
            "patternIngester",
            "ruler",
            "overridesExporter",
            "adminApi",
        )
        for group in zero_groups:
            self.assertEqual(self.values[group]["replicas"], 0, group)
        self.assertFalse(self.values["minio"]["enabled"])
        self.assertFalse(self.values["chunksCache"]["enabled"])
        self.assertFalse(self.values["resultsCache"]["enabled"])
        self.assertFalse(self.values["lokiCanary"]["enabled"])
        self.assertFalse(self.values["test"]["enabled"])
        self.assertFalse(self.values["sidecar"]["rules"]["enabled"])

    def test_filesystem_configuration_needs_no_runtime_secret(self) -> None:
        storage = self.values["loki"]["storage"]
        self.assertEqual(storage, {"type": "filesystem"})
        self.assertNotIn("extraEnvFrom", self.values["singleBinary"])
        self.assertNotIn("extraArgs", self.values["singleBinary"])
        self.assertEqual(self.activation["storage"]["type"], "filesystem")

    def test_retention_and_local_working_state_are_bounded(self) -> None:
        limits = self.values["loki"]["limits_config"]
        compactor = self.values["loki"]["compactor"]
        persistence = self.values["singleBinary"]["persistence"]
        self.assertEqual(limits["retention_period"], "72h")
        self.assertTrue(compactor["retention_enabled"])
        self.assertEqual(compactor["retention_delete_delay"], "2h")
        self.assertEqual(compactor["delete_request_store"], "filesystem")
        self.assertEqual(persistence["storageClass"], "longhorn-critical")
        self.assertEqual(persistence["size"], "5Gi")
        self.assertEqual(persistence["whenDeleted"], "Retain")
        self.assertEqual(self.activation["storage"]["storage_class"], "longhorn-critical")

    def test_loki_is_internal_and_capacity_input_matches_values(self) -> None:
        self.assertEqual(self.values["gateway"]["service"]["type"], "ClusterIP")
        self.assertFalse(self.values["gateway"]["ingress"]["enabled"])
        self.assertFalse(self.values["networkPolicy"]["enabled"])
        policies = {
            item["metadata"]["name"]: item for item in self.values["extraObjects"]
        }
        self.assertEqual(
            set(policies),
            {
                "loki-default-deny",
                "loki-internal",
                "loki-alloy-ingress",
                "loki-prometheus-ingress",
                "loki-cluster-dns",
            },
        )
        alloy = policies["loki-alloy-ingress"]["spec"]["ingress"][0]["from"][0]
        self.assertEqual(
            alloy["namespaceSelector"]["matchLabels"],
            {"kubernetes.io/metadata.name": "logging"},
        )
        dns = policies["loki-cluster-dns"]["spec"]["egress"][0]["to"][0]
        self.assertEqual(
            dns["podSelector"]["matchLabels"],
            {"k8s-app": "kube-dns"},
        )
        stateful = self.capacity["workloads"]["loki-single-binary"]
        gateway = self.capacity["workloads"]["loki-gateway"]
        self.assertEqual(stateful["requests"], self.values["singleBinary"]["resources"]["requests"])
        self.assertEqual(gateway["requests"], self.values["gateway"]["resources"]["requests"])
        self.assertEqual(stateful["persistent_volume"]["logical_size"], "5Gi")
        self.assertEqual(
            self.values["monitoring"]["serviceMonitor"]["labels"][
                "platform.verda-demo.io/monitor"
            ],
            "true",
        )


class Phase6AlloyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.versions = load_one(LOCK)
        cls.values = load_one(ALLOY / "values.yaml")
        cls.image_lock = load_one(ALLOY / "image-lock.yaml")
        cls.capacity = load_one(ALLOY / "capacity-input.yaml")
        cls.config = cls.values["alloy"]["configMap"]["content"]

    def test_chart_provenance_and_image_lock_are_exact_but_activation_is_closed(self) -> None:
        chart = self.versions["helm_charts"]["alloy"]
        self.assertEqual(chart["version"], "1.11.1")
        self.assertEqual(chart["app_version"], "v1.18.1")
        self.assertEqual(chart["archive_sha256"], self.image_lock["chart"]["archive_sha256"])
        self.assertIn("pending", chart["selection_status"])
        self.assertEqual(self.image_lock["activation_status"], "blocked")
        self.assertTrue(self.image_lock["blocking_gates"]["loki_activation_contract_ready"])
        locked = chart["images"]["alloy"]["digest"]
        self.assertEqual(self.values["image"]["digest"], locked)
        self.assertEqual(self.image_lock["required_images"][0]["digest"], locked)
        self.assertTrue(
            self.image_lock["blocking_gates"]["immutable_image_digest_locked"]
        )
        self.assertFalse(self.image_lock["blocking_gates"]["root_application_allowed"])
        self.assertFalse(self.values["configReloader"]["enabled"])

    def test_daemonset_collects_clustered_pod_logs_and_events(self) -> None:
        self.assertEqual(self.values["controller"]["type"], "daemonset")
        self.assertTrue(self.values["alloy"]["clustering"]["enabled"])
        self.assertIn('loki.source.kubernetes "pod_logs"', self.config)
        self.assertIn('loki.source.kubernetes_events "cluster_events"', self.config)
        self.assertIn('field = "spec.nodeName=" + sys.env("HOSTNAME")', self.config)
        self.assertEqual(self.config.count("clustering {"), 2)
        self.assertEqual(self.config.count("enabled = true"), 2)

    def test_no_host_or_journald_mounts_exist(self) -> None:
        mounts = self.values["alloy"]["mounts"]
        self.assertFalse(mounts["varlog"])
        self.assertFalse(mounts["dockercontainers"])
        rendered = (ALLOY / "values.yaml").read_text(encoding="utf-8").lower()
        for forbidden in (
            "/var/log/journal",
            "/run/log/journal",
            "/var/lib/rancher/rke2",
            "hostpath:",
            "hostpid: true",
            "hostnetwork: true",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_rbac_is_read_only_and_excludes_sensitive_resources(self) -> None:
        self.assertEqual(len(self.values["rbac"]["rules"]), 1)
        rule = self.values["rbac"]["rules"][0]
        self.assertEqual(set(rule["verbs"]), {"get", "list", "watch"})
        self.assertEqual(set(rule["resources"]), {"namespaces", "pods", "pods/log", "events"})
        cluster_rule = self.values["rbac"]["clusterRules"]
        self.assertEqual(len(cluster_rule), 1)
        self.assertEqual(cluster_rule[0]["resources"], ["pods"])
        self.assertEqual(set(cluster_rule[0]["verbs"]), {"get", "list", "watch"})
        for forbidden in ("secrets", "configmaps", "nodes", "deployments"):
            self.assertNotIn(forbidden, rule["resources"])

    def test_labels_and_structured_metadata_bound_cardinality(self) -> None:
        keep = re.search(r"stage\.label_keep \{\s*values = \[(.*?)\]\s*\}", self.config, re.S)
        self.assertIsNotNone(keep)
        assert keep is not None
        indexed = set(re.findall(r'"([a-z_]+)"', keep.group(1)))
        self.assertEqual(
            indexed,
            {"cluster", "namespace", "environment", "application", "container", "level"},
        )
        metadata = self.config.split("stage.structured_metadata", 1)[1].split("}", 2)[0]
        self.assertIn("pod", metadata)
        self.assertIn("request_id", metadata)
        self.assertIn("version", metadata)
        self.assertNotIn("request_id", indexed)
        self.assertNotIn("pod", indexed)

    def test_retry_backoff_metrics_and_capacity_are_deliberate(self) -> None:
        for required in (
            'batch_size          = "1MiB"',
            'batch_wait          = "1s"',
            'min_backoff_period  = "500ms"',
            'max_backoff_period  = "5m"',
            "max_backoff_retries = 10",
            "retry_on_http_429   = true",
        ):
            self.assertIn(required, self.config)
        self.assertTrue(self.values["serviceMonitor"]["enabled"])
        self.assertEqual(
            self.values["serviceMonitor"]["additionalLabels"][
                "platform.verda-demo.io/monitor"
            ],
            "true",
        )
        network = self.values["networkPolicy"]
        self.assertTrue(network["enabled"])
        self.assertEqual(set(network["policyTypes"]), {"Ingress", "Egress"})
        api_policy = self.values["extraObjects"][0]
        self.assertEqual(api_policy["kind"], "CiliumNetworkPolicy")
        self.assertEqual(
            api_policy["spec"]["egress"][0]["toEntities"],
            ["kube-apiserver"],
        )
        per_pod = self.capacity["workload"]["per_pod"]
        self.assertEqual(per_pod["requests"], self.values["alloy"]["resources"]["requests"])
        self.assertEqual(self.capacity["workload"]["expected_nodes"], 3)

    def test_saved_demo_dev_query_is_low_cardinality(self) -> None:
        query = (LOGQL / "demo-dev-logs.logql").read_text(encoding="utf-8").strip()
        self.assertEqual(query, '{cluster="management", namespace="demo-dev", application=~".+"}')
        for forbidden in ("request_id=", "pod=", "trace_id=", "user_id="):
            self.assertNotIn(forbidden, query)


class Phase6LoggingSecretSafetyTests(unittest.TestCase):
    def test_owned_files_contain_no_secret_object_or_literal_credentials(self) -> None:
        paths = [*LOKI.rglob("*"), *ALLOY.rglob("*"), *LOGQL.rglob("*")]
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^kind:\s*Secret\s*$", path)
            self.assertNotRegex(text, r"AKIA[0-9A-Z]{16}", path)
            self.assertNotRegex(text, r"(?m)^\s*(access_key|secret_key):\s*[^$<{\s]", path)


if __name__ == "__main__":
    unittest.main()
