#!/usr/bin/env python3
"""Prove Platform namespaces have bounded resources and default isolation."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


def documents(path: pathlib.Path) -> list[dict]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


class Phase6EnvironmentFoundationTests(unittest.TestCase):
    def test_platform_namespace_and_priority_taxonomy_is_exact(self) -> None:
        root = ROOT / "platform" / "management" / "namespaces"
        kustomization = yaml.safe_load(
            (root / "kustomization.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            kustomization["resources"],
            [
                "priorityclasses.yaml",
                "namespaces.yaml",
                "cattle-system-limit-range.yaml",
            ],
        )
        priorities = documents(root / "priorityclasses.yaml")
        self.assertEqual(
            {item["metadata"]["name"] for item in priorities},
            {"platform-critical", "platform-important", "platform-workload"},
        )
        self.assertEqual(sum(item["globalDefault"] for item in priorities), 0)
        self.assertLess(
            max(item["value"] for item in priorities), 2_000_000_000
        )
        namespaces = documents(root / "namespaces.yaml")
        self.assertEqual(
            {item["metadata"]["name"] for item in namespaces},
            {
                "sealed-secrets",
                "kyverno",
                "cattle-system",
                "harbor",
                "monitoring",
                "loki",
                "logging",
                "velero",
            },
        )
        for item in namespaces:
            labels = item["metadata"]["labels"]
            self.assertEqual(labels["platform.verda-demo.io/stage"], "platform")
            self.assertEqual(
                labels["pod-security.kubernetes.io/audit"], "restricted"
            )
            self.assertEqual(labels["pod-security.kubernetes.io/audit-version"], "v1.35")
        by_name = {item["metadata"]["name"]: item for item in namespaces}
        self.assertEqual(
            by_name["cattle-system"]["metadata"]["labels"][
                "pod-security.kubernetes.io/enforce"
            ],
            "baseline",
        )
        self.assertEqual(
            by_name["cattle-system"]["metadata"]["annotations"][
                "argocd.argoproj.io/sync-wave"
            ],
            "-20",
        )
        limit_range = documents(root / "cattle-system-limit-range.yaml")[0]
        self.assertEqual(limit_range["kind"], "LimitRange")
        self.assertEqual(limit_range["metadata"]["namespace"], "cattle-system")
        self.assertEqual(
            limit_range["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"],
            "-19",
        )
        self.assertEqual(
            limit_range["spec"]["limits"],
            [
                {
                    "type": "Container",
                    "defaultRequest": {"cpu": "100m", "memory": "128Mi"},
                    "default": {"cpu": "500m", "memory": "256Mi"},
                }
            ],
        )
        self.assertEqual(
            by_name["logging"]["metadata"]["labels"][
                "pod-security.kubernetes.io/enforce"
            ],
            "restricted",
        )

    def test_each_environment_has_the_complete_foundation(self) -> None:
        for environment in ("dev", "staging", "prod"):
            namespace = f"demo-{environment}"
            root = ROOT / "environments" / environment / "namespace"
            with self.subTest(environment=environment):
                kustomization = yaml.safe_load(
                    (root / "kustomization.yaml").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    set(kustomization["resources"]),
                    {
                        "namespace.yaml",
                        "quota.yaml",
                        "limitrange.yaml",
                        "network-policies.yaml",
                        "access.yaml",
                        "registry-credentials.yaml",
                    },
                )
                namespace_doc = documents(root / "namespace.yaml")[0]
                self.assertEqual(namespace_doc["metadata"]["name"], namespace)
                labels = namespace_doc["metadata"]["labels"]
                self.assertEqual(labels["pod-security.kubernetes.io/enforce"], "restricted")
                self.assertEqual(
                    labels["platform.verda-demo.io/topology"],
                    "platform-management-cluster",
                )
                quota = documents(root / "quota.yaml")[0]
                self.assertEqual(quota["metadata"]["namespace"], namespace)
                self.assertIn("requests.cpu", quota["spec"]["hard"])
                limit = documents(root / "limitrange.yaml")[0]
                self.assertEqual(limit["metadata"]["namespace"], namespace)
                self.assertEqual(limit["spec"]["limits"][0]["type"], "Container")

    def test_default_deny_and_dns_are_separate_and_exact(self) -> None:
        for environment in ("dev", "staging", "prod"):
            policies = documents(
                ROOT
                / "environments"
                / environment
                / "namespace"
                / "network-policies.yaml"
            )
            by_name = {item["metadata"]["name"]: item for item in policies}
            with self.subTest(environment=environment):
                deny = by_name["default-deny"]["spec"]
                self.assertEqual(deny["podSelector"], {})
                self.assertEqual(set(deny["policyTypes"]), {"Ingress", "Egress"})
                self.assertNotIn("ingress", deny)
                self.assertNotIn("egress", deny)
                dns = by_name["allow-cluster-dns"]["spec"]["egress"]
                ports = dns[0]["ports"]
                self.assertEqual(
                    {(item["protocol"], item["port"]) for item in ports},
                    {("UDP", 53), ("TCP", 53)},
                )
                peer = dns[0]["to"][0]
                self.assertEqual(
                    peer["namespaceSelector"]["matchLabels"],
                    {"kubernetes.io/metadata.name": "kube-system"},
                )
                self.assertEqual(peer["podSelector"]["matchLabels"], {"k8s-app": "kube-dns"})
                solver = by_name["allow-acme-http01-from-traefik"]["spec"]
                self.assertEqual(
                    solver["podSelector"]["matchLabels"],
                    {"acme.cert-manager.io/http01-solver": "true"},
                )
                ingress = solver["ingress"]
                self.assertEqual(ingress[0]["ports"], [{"protocol": "TCP", "port": 8089}])
                source = ingress[0]["from"][0]
                self.assertEqual(
                    source["namespaceSelector"]["matchLabels"],
                    {"kubernetes.io/metadata.name": "kube-system"},
                )
                self.assertEqual(
                    source["podSelector"]["matchLabels"],
                    {"app.kubernetes.io/name": "rke2-traefik"},
                )

    def test_access_and_registry_material_are_secret_safe_and_fail_closed(self) -> None:
        ciphertexts: set[str] = set()
        for environment in ("dev", "staging", "prod"):
            root = ROOT / "environments" / environment / "namespace"
            access = documents(root / "access.yaml")
            service_account = next(item for item in access if item["kind"] == "ServiceAccount")
            role_bindings = {
                item["metadata"]["name"]: item
                for item in access
                if item["kind"] == "RoleBinding"
            }
            self.assertFalse(service_account["automountServiceAccountToken"])
            self.assertEqual(
                service_account["imagePullSecrets"], [{"name": "platform-demo-registry"}]
            )
            self.assertEqual(role_bindings["verda-reviewers-view"]["roleRef"]["name"], "view")
            backup_binding = role_bindings["velero-backup-reader"]
            self.assertEqual(
                backup_binding["roleRef"]["name"],
                "velero-namespaced-backup-reader",
            )
            self.assertEqual(
                backup_binding["subjects"],
                [{"kind": "ServiceAccount", "name": "velero", "namespace": "velero"}],
            )
            sealed = documents(root / "registry-credentials.yaml")[0]
            self.assertEqual(sealed["kind"], "SealedSecret")
            self.assertEqual(
                sealed["metadata"]["annotations"]["sealedsecrets.bitnami.com/strict"],
                "true",
            )
            encrypted = sealed["spec"]["encryptedData"]
            self.assertEqual(set(encrypted), {".dockerconfigjson"})
            value = encrypted[".dockerconfigjson"]
            self.assertRegex(value, r"^REQUIRED_SEALED_CIPHERTEXT_[A-Z_]+$")
            ciphertexts.add(value)
            self.assertNotIn("data", sealed["spec"]["template"])
            self.assertNotIn("stringData", sealed["spec"]["template"])
        self.assertEqual(len(ciphertexts), 3)


if __name__ == "__main__":
    unittest.main()
