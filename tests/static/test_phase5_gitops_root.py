#!/usr/bin/env python3
"""Prove the Phase 5 root Application has ordered, non-overlapping ownership."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
GITOPS_ROOT = ROOT / "gitops" / "root"
REPOSITORY = "https://github.com/kaycee1771/verda-platform-takehome.git"


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Phase5GitOpsRootTests(unittest.TestCase):
    def test_root_has_only_the_live_verified_phase_five_children(self) -> None:
        kustomization = load(GITOPS_ROOT / "kustomization.yaml")
        self.assertEqual(
            kustomization["resources"],
            [
                "platform-project.yaml",
                "cert-manager-controller.yaml",
                "cert-manager-staging.yaml",
                "cert-manager-production.yaml",
                "argocd-ingress.yaml",
                "longhorn-prerequisites.yaml",
                "longhorn-controller.yaml",
                "longhorn-resources.yaml",
            ],
        )

    def test_project_fixed_point_precedes_children(self) -> None:
        bootstrap = load(GITOPS_ROOT / "platform-project.yaml")
        self.assertEqual(bootstrap["kind"], "Application")
        self.assertEqual(bootstrap["spec"]["project"], "platform-bootstrap")
        self.assertEqual(bootstrap["spec"]["source"], {
            "repoURL": REPOSITORY,
            "targetRevision": "main",
            "path": "gitops/appprojects",
        })
        self.assertEqual(bootstrap["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-20")
        self.assertFalse(bootstrap["spec"]["syncPolicy"]["automated"]["prune"])

        project = load(ROOT / "gitops" / "appprojects" / "platform.yaml")
        self.assertEqual(project["kind"], "AppProject")
        self.assertEqual(project["metadata"]["name"], "platform")
        self.assertEqual(set(project["spec"]["sourceRepos"]), {
            REPOSITORY,
            "https://charts.jetstack.io",
            "https://charts.longhorn.io",
        })
        destinations = {
            item["namespace"] for item in project["spec"]["destinations"]
        }
        self.assertEqual(destinations, {"argocd", "cert-manager", "longhorn-system"})

    def test_foundation_apps_are_ordered_and_git_owned(self) -> None:
        expected = {
            "cert-manager-controller.yaml": ("cert-manager-controller", "-15", "cert-manager"),
            "cert-manager-staging.yaml": ("argocd-certificate-staging", "-12", "argocd"),
            "cert-manager-production.yaml": ("argocd-certificate-production", "-8", "argocd"),
            "argocd-ingress.yaml": ("argocd-public-ingress", "-7", "argocd"),
            "longhorn-prerequisites.yaml": ("longhorn-prerequisites", "-11", "longhorn-system"),
            "longhorn-controller.yaml": ("longhorn-controller", "-10", "longhorn-system"),
            "longhorn-resources.yaml": ("longhorn-resources", "-9", "longhorn-system"),
        }
        for filename, (name, wave, namespace) in expected.items():
            with self.subTest(filename=filename):
                app = load(GITOPS_ROOT / filename)
                self.assertEqual(app["kind"], "Application")
                self.assertEqual(app["metadata"]["name"], name)
                self.assertEqual(app["metadata"]["namespace"], "argocd")
                self.assertEqual(
                    app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"],
                    wave,
                )
                self.assertEqual(app["spec"]["project"], "platform")
                self.assertEqual(app["spec"]["destination"], {
                    "server": "https://kubernetes.default.svc",
                    "namespace": namespace,
                })
                automated = app["spec"]["syncPolicy"]["automated"]
                expected_prune = filename != "longhorn-controller.yaml"
                self.assertEqual(automated, {
                    "prune": expected_prune,
                    "selfHeal": True,
                    "allowEmpty": False,
                })

        waves = {
            filename: int(load(GITOPS_ROOT / filename)["metadata"]["annotations"][
                "argocd.argoproj.io/sync-wave"
            ])
            for filename in (
                "longhorn-prerequisites.yaml",
                "longhorn-controller.yaml",
                "longhorn-resources.yaml",
            )
        }
        self.assertLess(
            waves["longhorn-prerequisites.yaml"],
            waves["longhorn-controller.yaml"],
        )
        self.assertLess(
            waves["longhorn-controller.yaml"],
            waves["longhorn-resources.yaml"],
        )

    def test_chart_apps_use_exact_versions_and_git_value_files(self) -> None:
        cert = load(GITOPS_ROOT / "cert-manager-controller.yaml")
        cert_chart, cert_values = cert["spec"]["sources"]
        self.assertEqual(
            (cert_chart["repoURL"], cert_chart["chart"], cert_chart["targetRevision"]),
            ("https://charts.jetstack.io", "cert-manager", "v1.21.1"),
        )
        self.assertEqual(
            cert_chart["helm"]["valueFiles"],
            ["$values/platform/management/cert-manager/controller-values.yaml"],
        )
        self.assertEqual(cert_values, {
            "repoURL": REPOSITORY,
            "targetRevision": "main",
            "ref": "values",
        })

        longhorn = load(GITOPS_ROOT / "longhorn-controller.yaml")
        chart, values = longhorn["spec"]["sources"]
        self.assertEqual(
            (chart["repoURL"], chart["chart"], chart["targetRevision"]),
            ("https://charts.longhorn.io", "longhorn", "1.12.1"),
        )
        self.assertEqual(
            chart["helm"]["valueFiles"],
            ["$values/platform/management/longhorn/values.yaml"],
        )
        self.assertEqual(values, cert_values)

    def test_longhorn_apps_have_disjoint_ordered_ownership(self) -> None:
        prerequisites = load(GITOPS_ROOT / "longhorn-prerequisites.yaml")
        resources = load(GITOPS_ROOT / "longhorn-resources.yaml")
        controller = load(GITOPS_ROOT / "longhorn-controller.yaml")

        self.assertEqual(
            prerequisites["spec"]["source"],
            {
                "repoURL": REPOSITORY,
                "targetRevision": "main",
                "path": "platform/management/longhorn/prerequisites",
            },
        )
        self.assertEqual(
            resources["spec"]["source"],
            {
                "repoURL": REPOSITORY,
                "targetRevision": "main",
                "path": "platform/management/longhorn/resources",
            },
        )
        self.assertNotIn(
            "CreateNamespace=true",
            controller["spec"]["syncPolicy"]["syncOptions"],
        )

    def test_staging_values_are_concrete_but_production_remains_gated(self) -> None:
        staging = load(
            ROOT / "platform" / "management" / "cert-manager" / "staging" / "values.yaml"
        )
        production = load(
            ROOT / "platform" / "management" / "cert-manager" / "production" / "values.yaml"
        )
        ingress = load(
            ROOT / "platform" / "management" / "ingress" / "argocd" / "values.yaml"
        )
        self.assertRegex(staging["hostname"], r"^argocd\.(?:\d{1,3}-){3}\d{1,3}\.sslip\.io$")
        self.assertIn("@", staging["acmeEmail"])
        self.assertEqual(production["hostname"], staging["hostname"])
        self.assertEqual(production["acmeEmail"], staging["acmeEmail"])
        self.assertTrue(production["stagingIssuerVerified"])
        self.assertEqual(ingress["hostname"], staging["hostname"])
        self.assertTrue(all(value is True for value in ingress["gates"].values()))


if __name__ == "__main__":
    unittest.main()
