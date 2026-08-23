#!/usr/bin/env python3
"""Lock namespace-local Phase 6 target monitors and their ingress boundaries."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
TARGETS = ROOT / "platform" / "management" / "monitoring" / "targets"

EXPECTED = {
    "argocd": {
        "namespace": "argocd",
        "monitor": "argocd-components",
        "port": "http-metrics",
        "policy": "argocd-prometheus-ingress",
        "policy_ports": {8080, 8082, 8083, 8084},
    },
    "harbor": {
        "namespace": "harbor",
        "monitor": "harbor",
        "port": "http-metrics",
        "policy": "harbor-prometheus-ingress",
        "policy_ports": {8001},
    },
    "longhorn": {
        "namespace": "longhorn-system",
        "monitor": "longhorn-manager",
        "port": "manager",
        "policy": "longhorn-prometheus-ingress",
        "policy_ports": {9500},
    },
    "rancher": {
        "namespace": "cattle-system",
        "monitor": "rancher",
        "port": "http",
        "policy": "rancher-prometheus-ingress",
        "policy_ports": {80},
    },
    "traefik": {
        "namespace": "kube-system",
        "monitor": "rke2-traefik",
        "port": "metrics",
        "policy": "rke2-traefik-prometheus-ingress",
        "policy_ports": {"metrics"},
    },
}


def load_documents(path: pathlib.Path) -> list[dict]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


class Phase6TargetMonitorTests(unittest.TestCase):
    def test_each_target_has_one_monitor_and_one_ingress_policy(self) -> None:
        self.assertEqual(
            {path.name for path in TARGETS.iterdir() if path.is_dir()}, set(EXPECTED)
        )
        for target, expected in EXPECTED.items():
            with self.subTest(target=target):
                directory = TARGETS / target
                kustomization = yaml.safe_load(
                    (directory / "kustomization.yaml").read_text(encoding="utf-8")
                )
                self.assertEqual(kustomization["resources"], ["monitoring.yaml"])
                objects = load_documents(directory / "monitoring.yaml")
                self.assertEqual(
                    [item["kind"] for item in objects],
                    ["ServiceMonitor", "NetworkPolicy"],
                )
                monitor, policy = objects
                self.assertEqual(monitor["metadata"]["name"], expected["monitor"])
                self.assertEqual(monitor["metadata"]["namespace"], expected["namespace"])
                self.assertEqual(
                    monitor["metadata"]["labels"]["platform.verda-demo.io/monitor"],
                    "true",
                )
                self.assertEqual(
                    monitor["spec"]["namespaceSelector"],
                    {"matchNames": [expected["namespace"]]},
                )
                self.assertEqual(len(monitor["spec"]["endpoints"]), 1)
                endpoint = monitor["spec"]["endpoints"][0]
                self.assertEqual(endpoint["port"], expected["port"])
                self.assertEqual(endpoint["path"], "/metrics")
                self.assertEqual(endpoint["scheme"], "http")
                self.assertEqual(policy["metadata"]["name"], expected["policy"])
                self.assertEqual(policy["metadata"]["namespace"], expected["namespace"])
                self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])

    def test_prometheus_sources_are_exact_and_ports_are_target_specific(self) -> None:
        for target, expected in EXPECTED.items():
            with self.subTest(target=target):
                policy = load_documents(TARGETS / target / "monitoring.yaml")[1]
                prometheus_rules = []
                for rule in policy["spec"]["ingress"]:
                    sources = rule.get("from", [])
                    if sources == [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "monitoring"
                                }
                            },
                            "podSelector": {
                                "matchLabels": {
                                    "app.kubernetes.io/name": "prometheus"
                                }
                            },
                        }
                    ]:
                        prometheus_rules.append(rule)
                self.assertEqual(len(prometheus_rules), 1)
                self.assertEqual(
                    {entry["port"] for entry in prometheus_rules[0]["ports"]},
                    expected["policy_ports"],
                )
                self.assertTrue(
                    all(entry["protocol"] == "TCP" for entry in prometheus_rules[0]["ports"])
                )

    def test_preservation_rules_are_explicit_and_bounded(self) -> None:
        argocd = load_documents(TARGETS / "argocd" / "monitoring.yaml")[1]
        longhorn = load_documents(TARGETS / "longhorn" / "monitoring.yaml")[1]
        self.assertEqual(argocd["spec"]["ingress"][0], {"from": [{"podSelector": {}}]})
        self.assertEqual(longhorn["spec"]["ingress"][0], {"from": [{"podSelector": {}}]})

        traefik = load_documents(TARGETS / "traefik" / "monitoring.yaml")[1]
        public = traefik["spec"]["ingress"][0]
        self.assertEqual(public["from"], [{"ipBlock": {"cidr": "0.0.0.0/0"}}])
        self.assertEqual(
            {(entry["port"], entry["protocol"]) for entry in public["ports"]},
            {("web", "TCP"), ("websecure", "TCP")},
        )

    def test_component_owners_no_longer_own_monitor_ingress(self) -> None:
        harbor = (
            ROOT
            / "platform/management/harbor/service/templates/network-policies.yaml"
        ).read_text(encoding="utf-8")
        rancher = (
            ROOT / "platform/management/rancher/templates/network-policy.yaml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("harbor-metrics-ingress", harbor)
        self.assertNotIn("kubernetes.io/metadata.name: monitoring", rancher)


if __name__ == "__main__":
    unittest.main()
