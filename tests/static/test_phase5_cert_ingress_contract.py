#!/usr/bin/env python3
"""Phase 5 cert-manager and authenticated ingress contract tests."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
CERT = ROOT / "platform" / "management" / "cert-manager"
INGRESS = ROOT / "platform" / "management" / "ingress" / "argocd"
SAFE_HOSTNAME = "argocd.192-0-2-10.sslip.io"
SAFE_EMAIL = "platform@example.com"


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: pathlib.Path) -> dict:
    return yaml.safe_load(read_text(path))


def helm_template(chart: pathlib.Path, *settings: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise unittest.SkipTest("helm is supplied by the pinned quality image")

    command = [
        helm,
        "template",
        "phase5-contract",
        str(chart),
        "--namespace",
        "argocd",
        "--kube-version",
        "1.35.7",
    ]
    for setting in settings:
        command.extend(("--set", setting))
    return subprocess.run(command, check=False, capture_output=True, text=True)


def rendered_objects(output: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]


class Phase5CertIngressContractTests(unittest.TestCase):
    def test_controller_values_pin_crd_lifecycle_and_bounded_replicas(self) -> None:
        values = load_yaml(CERT / "controller-values.yaml")
        self.assertEqual(values["global"]["leaderElection"]["namespace"], "cert-manager")
        self.assertEqual(values["crds"], {"enabled": True, "keep": True})
        self.assertFalse(values["enableCertificateOwnerRef"])
        self.assertFalse(values["enableServiceLinks"])

        image_digests = {
            values["image"]["digest"],
            values["webhook"]["image"]["digest"],
            values["cainjector"]["image"]["digest"],
            values["acmesolver"]["image"]["digest"],
            values["startupapicheck"]["image"]["digest"],
        }
        self.assertEqual(len(image_digests), 5)
        for digest in image_digests:
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

        for component in (values, values["webhook"], values["cainjector"]):
            self.assertEqual(component["replicaCount"], 2)
            self.assertEqual(
                component["podDisruptionBudget"],
                {"enabled": True, "minAvailable": 1},
            )
            self.assertTrue(component["securityContext"]["runAsNonRoot"])
            self.assertEqual(
                component["securityContext"]["seccompProfile"]["type"],
                "RuntimeDefault",
            )
            self.assertFalse(
                component["containerSecurityContext"]["allowPrivilegeEscalation"]
            )
            self.assertEqual(
                component["containerSecurityContext"]["capabilities"]["drop"],
                ["ALL"],
            )
            self.assertTrue(
                component["containerSecurityContext"]["readOnlyRootFilesystem"]
            )
            self.assertIn("requests", component["resources"])
            self.assertIn("limits", component["resources"])

        self.assertTrue(values["startupapicheck"]["enabled"])
        self.assertTrue(values["prometheus"]["enabled"])
        self.assertFalse(values["prometheus"]["servicemonitor"]["enabled"])

    def test_local_charts_are_exactly_scoped_to_the_locked_platform_versions(self) -> None:
        staging = load_yaml(CERT / "staging" / "Chart.yaml")
        production = load_yaml(CERT / "production" / "Chart.yaml")
        ingress = load_yaml(INGRESS / "Chart.yaml")

        self.assertEqual(staging["appVersion"], "v1.21.1")
        self.assertEqual(production["appVersion"], "v1.21.1")
        self.assertEqual(ingress["appVersion"], "v3.5.1")
        for chart in (staging, production, ingress):
            self.assertEqual(chart["kubeVersion"], ">=1.35.0-0 <1.36.0-0")

    def test_values_schemas_reject_unknowns_and_only_accept_the_traefik_path(self) -> None:
        for chart in (CERT / "staging", CERT / "production", INGRESS):
            schema = json.loads(read_text(chart / "values.schema.json"))
            self.assertFalse(schema["additionalProperties"])
            self.assertRegex(
                SAFE_HOSTNAME,
                schema["properties"]["hostname"]["pattern"],
            )

        for chart in (CERT / "staging", CERT / "production"):
            schema = json.loads(read_text(chart / "values.schema.json"))
            self.assertEqual(
                schema["properties"]["ingressClassName"]["const"], "traefik"
            )

        ingress_schema = json.loads(read_text(INGRESS / "values.schema.json"))
        self.assertIn("networkPolicyOwner", ingress_schema["required"])
        self.assertEqual(
            ingress_schema["properties"]["networkPolicyOwner"]["const"],
            "bootstrap-helm",
        )

    def test_staging_is_namespaced_http01_and_contains_no_secret_or_ingress(self) -> None:
        result = helm_template(
            CERT / "staging",
            f"hostname={SAFE_HOSTNAME}",
            f"acmeEmail={SAFE_EMAIL}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = rendered_objects(result.stdout)
        self.assertEqual({item["kind"] for item in objects}, {"Issuer", "Certificate"})

        issuer = next(item for item in objects if item["kind"] == "Issuer")
        certificate = next(item for item in objects if item["kind"] == "Certificate")
        self.assertEqual(issuer["metadata"]["namespace"], "argocd")
        self.assertEqual(
            issuer["spec"]["acme"]["server"],
            "https://acme-staging-v02.api.letsencrypt.org/directory",
        )
        solver = issuer["spec"]["acme"]["solvers"][0]["http01"]["ingress"]
        self.assertEqual(solver["ingressClassName"], "traefik")
        self.assertEqual(solver["serviceType"], "ClusterIP")
        self.assertEqual(certificate["spec"]["secretName"], "argocd-staging-tls")
        self.assertEqual(certificate["spec"]["dnsNames"], [SAFE_HOSTNAME])

    def test_production_issuance_fails_closed_until_staging_is_proven(self) -> None:
        blocked = helm_template(
            CERT / "production",
            f"hostname={SAFE_HOSTNAME}",
            f"acmeEmail={SAFE_EMAIL}",
            "stagingIssuerVerified=false",
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("stagingIssuerVerified=true", blocked.stderr)

        allowed = helm_template(
            CERT / "production",
            f"hostname={SAFE_HOSTNAME}",
            f"acmeEmail={SAFE_EMAIL}",
            "stagingIssuerVerified=true",
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        objects = rendered_objects(allowed.stdout)
        self.assertEqual({item["kind"] for item in objects}, {"Issuer", "Certificate"})
        issuer = next(item for item in objects if item["kind"] == "Issuer")
        certificate = next(item for item in objects if item["kind"] == "Certificate")
        self.assertEqual(
            issuer["spec"]["acme"]["server"],
            "https://acme-v02.api.letsencrypt.org/directory",
        )
        self.assertEqual(certificate["spec"]["secretName"], "argocd-ingress-tls")

    def test_invalid_or_non_sslip_hostname_is_rejected_before_render(self) -> None:
        for hostname in (
            "argocd.example.com",
            "argocd.999-0-2-10.sslip.io",
            "argocd.192-0-2.sslip.io",
        ):
            with self.subTest(hostname=hostname):
                result = helm_template(
                    CERT / "staging",
                    f"hostname={hostname}",
                    f"acmeEmail={SAFE_EMAIL}",
                )
                self.assertNotEqual(result.returncode, 0)

    def test_ingress_is_blocked_until_certificate_and_authentication_are_proven(self) -> None:
        for settings, expected in (
            ((), "productionCertificateVerified=true"),
            (("gates.productionCertificateVerified=true",), "argocdAuthenticationVerified=true"),
            (
                (
                    "gates.productionCertificateVerified=true",
                    "gates.argocdAuthenticationVerified=true",
                ),
                "argocdInternalHttpVerified=true",
            ),
        ):
            with self.subTest(expected=expected):
                result = helm_template(
                    INGRESS,
                    f"hostname={SAFE_HOSTNAME}",
                    *settings,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_ingress_rejects_any_network_policy_owner_other_than_bootstrap_helm(self) -> None:
        result = helm_template(
            INGRESS,
            f"hostname={SAFE_HOSTNAME}",
            "networkPolicyOwner=public-ingress-chart",
            "gates.productionCertificateVerified=true",
            "gates.argocdAuthenticationVerified=true",
            "gates.argocdInternalHttpVerified=true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("networkPolicyOwner", result.stderr)

    def test_ingress_uses_rke2_traefik_tls_and_grpc_web_compatible_http(self) -> None:
        result = helm_template(
            INGRESS,
            f"hostname={SAFE_HOSTNAME}",
            "gates.productionCertificateVerified=true",
            "gates.argocdAuthenticationVerified=true",
            "gates.argocdInternalHttpVerified=true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = rendered_objects(result.stdout)
        self.assertEqual([item["kind"] for item in objects], ["Ingress"])

        ingress = next(item for item in objects if item["kind"] == "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "traefik")
        self.assertEqual(ingress["spec"]["tls"][0]["hosts"], [SAFE_HOSTNAME])
        self.assertEqual(
            ingress["spec"]["tls"][0]["secretName"], "argocd-ingress-tls"
        )
        self.assertEqual(ingress["spec"]["rules"][0]["host"], SAFE_HOSTNAME)
        backend_port = ingress["spec"]["rules"][0]["http"]["paths"][0][
            "backend"
        ]["service"]["port"]
        self.assertEqual(backend_port, {"name": "http"})
        annotations = ingress["metadata"]["annotations"]
        self.assertEqual(
            annotations["traefik.ingress.kubernetes.io/router.entrypoints"],
            "websecure",
        )
        self.assertEqual(
            annotations["verda.platform/authentication-boundary"], "argocd-rbac"
        )
        self.assertEqual(annotations["verda.platform/cli-mode"], "grpc-web")
        self.assertEqual(
            annotations["verda.platform/network-policy-owner"], "bootstrap-helm"
        )

        rendered = result.stdout.lower()
        for forbidden in (
            "insecureskipverify",
            "passthrough",
            "certresolver",
            "nodeport",
            "loadbalancer",
            "kind: secret",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_bootstrap_helm_is_the_only_argocd_server_network_policy_owner(self) -> None:
        result = helm_template(
            INGRESS,
            f"hostname={SAFE_HOSTNAME}",
            "gates.productionCertificateVerified=true",
            "gates.argocdAuthenticationVerified=true",
            "gates.argocdInternalHttpVerified=true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((INGRESS / "templates" / "network-policy.yaml").exists())
        self.assertFalse(
            any(item["kind"] == "NetworkPolicy" for item in rendered_objects(result.stdout))
        )

        bootstrap = load_yaml(ROOT / "bootstrap" / "argocd" / "values.yaml")
        policies = [
            item for item in bootstrap["extraObjects"] if item["kind"] == "NetworkPolicy"
        ]
        self.assertEqual(len(policies), 1)
        policy = policies[0]
        self.assertEqual(policy["metadata"]["name"], "argocd-server-bootstrap-ingress")
        self.assertEqual(
            policy["spec"]["podSelector"]["matchLabels"],
            {"app.kubernetes.io/name": "argocd-server"},
        )
        source = policy["spec"]["ingress"][0]["from"][0]
        self.assertEqual(
            source["namespaceSelector"]["matchLabels"],
            {"kubernetes.io/metadata.name": "kube-system"},
        )
        self.assertEqual(
            source["podSelector"]["matchLabels"],
            {"app.kubernetes.io/name": "rke2-traefik"},
        )
        self.assertEqual(
            policy["spec"]["ingress"][0]["ports"],
            [{"protocol": "TCP", "port": 8080}],
        )

    def test_no_plaintext_secret_manifest_exists_in_owned_paths(self) -> None:
        for path in list(CERT.rglob("*")) + list(INGRESS.rglob("*")):
            if not path.is_file():
                continue
            text = read_text(path)
            self.assertNotIn("kind: Secret", text, path)
            self.assertNotIn("stringData:", text, path)
            self.assertIsNone(re.search(r"(?m)^data:\s*$", text), path)


if __name__ == "__main__":
    unittest.main()
