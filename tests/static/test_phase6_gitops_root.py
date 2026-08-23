#!/usr/bin/env python3
"""Prove the inert Phase 6 root candidate is exact, ordered, and fail closed."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
LIVE_ROOT = ROOT / "gitops" / "root"
CANDIDATE = LIVE_ROOT / "platform-services"
REPOSITORY = "https://github.com/kaycee1771/verda-platform-takehome.git"
SERVER = "https://kubernetes.default.svc"


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


EXPECTED_RESOURCES = [
    "prerequisites.yaml",
    "sealed-secrets.yaml",
    "kyverno-controller.yaml",
    "rancher.yaml",
    "harbor-secrets.yaml",
    "harbor-postgresql.yaml",
    "harbor-service.yaml",
    "monitoring-controller.yaml",
    "monitoring-resources.yaml",
    "loki.yaml",
    "alloy.yaml",
    "velero-controller.yaml",
    "velero-resources.yaml",
    "sealed-secrets-monitoring.yaml",
    "kyverno-monitoring.yaml",
    "kyverno-policies.yaml",
    "argocd-monitoring.yaml",
    "harbor-monitoring.yaml",
    "longhorn-monitoring.yaml",
    "rancher-monitoring.yaml",
    "traefik-monitoring.yaml",
    "environment-dev.yaml",
    "environment-staging.yaml",
    "environment-prod.yaml",
    "platform-demo-dev.yaml",
    "platform-demo-staging.yaml",
    "platform-demo-prod.yaml",
]

EXPECTED = {
    "prerequisites.yaml": ("platform-namespaces", "foundation", "argocd", -19),
    "sealed-secrets.yaml": ("sealed-secrets-controller", "security", "sealed-secrets", -15),
    "kyverno-controller.yaml": ("kyverno-controller", "security", "kyverno", -12),
    "rancher.yaml": ("rancher", "management", "cattle-system", -10),
    "harbor-secrets.yaml": ("harbor-secrets", "registry", "harbor", -9),
    "harbor-postgresql.yaml": ("harbor-postgresql", "registry", "harbor", -8),
    "harbor-service.yaml": ("harbor", "registry", "harbor", -7),
    "monitoring-controller.yaml": ("monitoring", "observability", "monitoring", -6),
    "monitoring-resources.yaml": ("monitoring-resources", "observability", "monitoring", -5),
    "loki.yaml": ("loki", "observability", "loki", -6),
    "alloy.yaml": ("alloy", "observability", "logging", -5),
    "velero-controller.yaml": ("velero-controller", "backup", "velero", -4),
    "velero-resources.yaml": ("velero-resources", "backup", "velero", -3),
    "sealed-secrets-monitoring.yaml": ("sealed-secrets-monitoring", "security", "sealed-secrets", -2),
    "kyverno-monitoring.yaml": ("kyverno-monitoring", "security", "kyverno", -2),
    "kyverno-policies.yaml": ("kyverno-policies", "security", "kyverno", -2),
    "argocd-monitoring.yaml": ("argocd-monitoring", "monitoring-targets", "argocd", -2),
    "harbor-monitoring.yaml": ("harbor-monitoring", "monitoring-targets", "harbor", -2),
    "longhorn-monitoring.yaml": ("longhorn-monitoring", "monitoring-targets", "longhorn-system", -2),
    "rancher-monitoring.yaml": ("rancher-monitoring", "monitoring-targets", "cattle-system", -2),
    "traefik-monitoring.yaml": ("traefik-monitoring", "monitoring-targets", "kube-system", -2),
    "environment-dev.yaml": ("demo-dev-foundation", "foundation", "demo-dev", 0),
    "environment-staging.yaml": ("demo-staging-foundation", "foundation", "demo-staging", 0),
    "environment-prod.yaml": ("demo-prod-foundation", "foundation", "demo-prod", 0),
    "platform-demo-dev.yaml": ("platform-demo-dev", "dev", "demo-dev", 10),
    "platform-demo-staging.yaml": ("platform-demo-staging", "staging", "demo-staging", 20),
    "platform-demo-prod.yaml": ("platform-demo-prod", "prod", "demo-prod", 20),
}


class Phase6GitOpsRootTests(unittest.TestCase):
    def test_candidate_is_complete_but_not_live_while_admission_is_blocked(self) -> None:
        self.assertEqual(load(CANDIDATE / "kustomization.yaml")["resources"], EXPECTED_RESOURCES)
        live_resources = load(LIVE_ROOT / "kustomization.yaml")["resources"]
        self.assertNotIn("platform-services", live_resources)
        self.assertNotIn("platform-services/kustomization.yaml", live_resources)
        capacity = load(ROOT / "config" / "platform-capacity-admission.yaml")
        self.assertEqual(capacity["admission_status"], "blocked-incomplete-inputs")

    def test_all_applications_have_exact_identity_destination_and_safe_source(self) -> None:
        self.assertEqual(set(EXPECTED), set(EXPECTED_RESOURCES))
        observed_names: set[str] = set()
        for filename, (name, project, namespace, wave) in EXPECTED.items():
            with self.subTest(filename=filename):
                app = load(CANDIDATE / filename)
                self.assertEqual(app["apiVersion"], "argoproj.io/v1alpha1")
                self.assertEqual(app["kind"], "Application")
                self.assertEqual(app["metadata"]["name"], name)
                self.assertEqual(app["metadata"]["namespace"], "argocd")
                self.assertEqual(
                    int(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                    wave,
                )
                self.assertEqual(app["spec"]["project"], project)
                self.assertEqual(
                    app["spec"]["destination"],
                    {"server": SERVER, "namespace": namespace},
                )
                observed_names.add(name)
                sources = app["spec"].get("sources", [app["spec"].get("source")])
                self.assertTrue(all(isinstance(source, dict) for source in sources))
                for source in sources:
                    self.assertNotIn(source.get("repoURL"), {None, "*"})
                    self.assertNotIn(source.get("targetRevision"), {None, "", "HEAD", "latest"})
                policy = app["spec"]["syncPolicy"]
                self.assertEqual(policy["automated"]["allowEmpty"], False)
                self.assertNotIn("CreateNamespace=true", policy.get("syncOptions", []))
        self.assertEqual(len(observed_names), len(EXPECTED))

    def test_external_charts_are_exact_and_use_git_owned_values(self) -> None:
        expected = {
            "sealed-secrets.yaml": ("https://bitnami.github.io/sealed-secrets", "sealed-secrets", "2.19.0"),
            "kyverno-controller.yaml": ("https://kyverno.github.io/kyverno", "kyverno", "3.8.2"),
            "monitoring-controller.yaml": ("https://prometheus-community.github.io/helm-charts", "kube-prometheus-stack", "88.3.0"),
            "loki.yaml": ("https://grafana.github.io/helm-charts", "loki", "7.3.0"),
            "alloy.yaml": ("https://grafana.github.io/helm-charts", "alloy", "1.11.1"),
            "velero-controller.yaml": ("https://vmware-tanzu.github.io/helm-charts", "velero", "12.1.0"),
        }
        for filename, chart_identity in expected.items():
            with self.subTest(filename=filename):
                chart, values = load(CANDIDATE / filename)["spec"]["sources"]
                self.assertEqual(
                    (chart["repoURL"], chart["chart"], chart["targetRevision"]),
                    chart_identity,
                )
                self.assertEqual(values, {
                    "repoURL": REPOSITORY,
                    "targetRevision": "main",
                    "ref": "values",
                })
                self.assertRegex(chart["helm"]["valueFiles"][0], r"^\$values/")

    def test_dependency_order_and_destructive_ownership_are_explicit(self) -> None:
        waves = {filename: details[3] for filename, details in EXPECTED.items()}
        for earlier, later in (
            ("prerequisites.yaml", "sealed-secrets.yaml"),
            ("sealed-secrets.yaml", "harbor-secrets.yaml"),
            ("harbor-secrets.yaml", "harbor-postgresql.yaml"),
            ("harbor-postgresql.yaml", "harbor-service.yaml"),
            ("monitoring-controller.yaml", "monitoring-resources.yaml"),
            ("monitoring-controller.yaml", "argocd-monitoring.yaml"),
            ("monitoring-controller.yaml", "harbor-monitoring.yaml"),
            ("monitoring-controller.yaml", "longhorn-monitoring.yaml"),
            ("monitoring-controller.yaml", "rancher-monitoring.yaml"),
            ("monitoring-controller.yaml", "traefik-monitoring.yaml"),
            ("velero-controller.yaml", "velero-resources.yaml"),
            ("environment-dev.yaml", "platform-demo-dev.yaml"),
            ("environment-staging.yaml", "platform-demo-staging.yaml"),
            ("environment-prod.yaml", "platform-demo-prod.yaml"),
        ):
            self.assertLess(waves[earlier], waves[later])

        preserve = {
            "prerequisites.yaml",
            "sealed-secrets.yaml",
            "kyverno-controller.yaml",
            "rancher.yaml",
            "harbor-secrets.yaml",
            "harbor-postgresql.yaml",
            "harbor-service.yaml",
            "monitoring-controller.yaml",
            "loki.yaml",
            "velero-controller.yaml",
            "velero-resources.yaml",
            "kyverno-policies.yaml",
            "environment-dev.yaml",
            "environment-staging.yaml",
            "environment-prod.yaml",
        }
        for filename in preserve:
            self.assertFalse(
                load(CANDIDATE / filename)["spec"]["syncPolicy"]["automated"]["prune"],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
