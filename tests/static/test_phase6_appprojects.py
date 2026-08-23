#!/usr/bin/env python3
"""Lock Phase 6 GitOps trust domains to exact sources and destinations."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
PROJECTS = ROOT / "gitops" / "appprojects"
GIT = "https://github.com/kaycee1771/verda-platform-takehome.git"
SERVER = "https://kubernetes.default.svc"


def load(name: str) -> dict:
    return yaml.safe_load((PROJECTS / name).read_text(encoding="utf-8"))


class Phase6AppProjectTests(unittest.TestCase):
    def test_kustomization_has_the_exact_phase_six_trust_domains(self) -> None:
        resources = load("kustomization.yaml")["resources"]
        self.assertEqual(
            resources,
            [
                "platform.yaml",
                "foundation.yaml",
                "security.yaml",
                "management.yaml",
                "registry.yaml",
                "observability.yaml",
                "backup.yaml",
                "monitoring-targets.yaml",
                "dev.yaml",
                "staging.yaml",
                "prod.yaml",
            ],
        )

    def test_component_projects_have_exact_sources_and_destinations(self) -> None:
        expected = {
            "foundation.yaml": (
                {GIT},
                {
                    "argocd",
                    "demo-dev",
                    "demo-staging",
                    "demo-prod",
                    "sealed-secrets",
                    "kyverno",
                    "cattle-system",
                    "harbor",
                    "monitoring",
                    "loki",
                    "logging",
                },
            ),
            "security.yaml": (
                {
                    GIT,
                    "https://bitnami.github.io/sealed-secrets",
                    "https://kyverno.github.io/kyverno",
                },
                {"sealed-secrets", "kyverno"},
            ),
            "management.yaml": (
                {GIT, "https://releases.rancher.com/server-charts/stable"},
                {"cattle-system"},
            ),
            "registry.yaml": (
                {GIT, "https://helm.goharbor.io"},
                {"harbor", "harbor-database"},
            ),
            "observability.yaml": (
                {
                    GIT,
                    "https://prometheus-community.github.io/helm-charts",
                    "https://grafana.github.io/helm-charts",
                },
                {"monitoring", "loki", "logging", "kube-system"},
            ),
            "backup.yaml": (
                {GIT, "https://vmware-tanzu.github.io/helm-charts"},
                {"velero"},
            ),
            "monitoring-targets.yaml": (
                {GIT},
                {"argocd", "cattle-system", "harbor", "kube-system", "longhorn-system"},
            ),
        }
        for filename, (sources, namespaces) in expected.items():
            with self.subTest(project=filename):
                document = load(filename)
                self.assertEqual(document["kind"], "AppProject")
                self.assertEqual(set(document["spec"]["sourceRepos"]), sources)
                self.assertNotIn("*", document["spec"]["sourceRepos"])
                destinations = document["spec"]["destinations"]
                self.assertEqual(
                    {item["namespace"] for item in destinations}, namespaces
                )
                self.assertTrue(
                    all(item["server"] == SERVER for item in destinations)
                )

    def test_environment_projects_cannot_escape_their_namespace(self) -> None:
        for project, namespace in (
            ("dev", "demo-dev"),
            ("staging", "demo-staging"),
            ("prod", "demo-prod"),
        ):
            with self.subTest(project=project):
                document = load(f"{project}.yaml")
                self.assertEqual(document["metadata"]["name"], project)
                self.assertEqual(document["spec"]["sourceRepos"], [GIT])
                self.assertEqual(
                    document["spec"]["destinations"],
                    [{"namespace": namespace, "server": SERVER}],
                )
                self.assertEqual(document["spec"]["clusterResourceWhitelist"], [])
                namespaced = {
                    (item["group"], item["kind"])
                    for item in document["spec"]["namespaceResourceWhitelist"]
                }
                self.assertNotIn(("*", "*"), namespaced)
                self.assertIn(("apps", "Deployment"), namespaced)
                self.assertIn(("networking.k8s.io", "NetworkPolicy"), namespaced)
                self.assertIn(("monitoring.coreos.com", "ServiceMonitor"), namespaced)
                self.assertIn(("cert-manager.io", "Issuer"), namespaced)
                self.assertNotIn(("", "Secret"), namespaced)
                self.assertNotIn(("", "ServiceAccount"), namespaced)

        foundation = load("foundation.yaml")
        foundation_kinds = {
            (item["group"], item["kind"])
            for item in foundation["spec"]["namespaceResourceWhitelist"]
        }
        self.assertIn(("bitnami.com", "SealedSecret"), foundation_kinds)

        security = load("security.yaml")
        security_cluster_kinds = {
            (item["group"], item["kind"])
            for item in security["spec"]["clusterResourceWhitelist"]
        }
        self.assertIn(("kyverno.io", "ClusterPolicy"), security_cluster_kinds)

        targets = load("monitoring-targets.yaml")
        self.assertEqual(targets["spec"]["clusterResourceWhitelist"], [])
        self.assertEqual(
            {
                (item["group"], item["kind"])
                for item in targets["spec"]["namespaceResourceWhitelist"]
            },
            {
                ("monitoring.coreos.com", "ServiceMonitor"),
                ("networking.k8s.io", "NetworkPolicy"),
            },
        )

    def test_reviewer_can_read_but_never_operate_phase_six_projects(self) -> None:
        values = yaml.safe_load(
            (ROOT / "bootstrap" / "argocd" / "values.yaml").read_text(
                encoding="utf-8"
            )
        )
        policy = values["configs"]["rbac"]["policy.csv"].splitlines()
        for project in (
            "foundation",
            "security",
            "management",
            "registry",
            "observability",
            "backup",
            "monitoring-targets",
            "dev",
            "staging",
            "prod",
        ):
            with self.subTest(project=project):
                self.assertIn(
                    f"p, role:reviewer, applications, get, {project}/*, allow",
                    policy,
                )
                self.assertIn(
                    f"p, role:reviewer, applications, sync, {project}/*, deny",
                    policy,
                )
                self.assertIn(
                    f"p, role:reviewer, applications, action/*, {project}/*, deny",
                    policy,
                )


if __name__ == "__main__":
    unittest.main()
