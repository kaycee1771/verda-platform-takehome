#!/usr/bin/env python3
"""Offline contract tests for the separate Phase 6 Platform demo workload."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).parents[2]
APP = ROOT / "applications" / "platform-demo"
CHART = APP / "chart"
ENVIRONMENTS = {
    "dev": ("demo-dev", 1),
    "staging": ("demo-staging", 1),
    "prod": ("demo-prod", 2),
}


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: pathlib.Path) -> dict:
    return yaml.safe_load(read_text(path))


def objects(output: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]


def helm_template(environment: str, *settings: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise unittest.SkipTest("helm is supplied by the pinned quality image")
    namespace, _ = ENVIRONMENTS[environment]
    command = [
        helm,
        "template",
        f"platform-demo-{environment}",
        str(CHART),
        "--namespace",
        namespace,
        "--kube-version",
        "1.35.7",
        "--values",
        str(APP / f"values-{environment}.yaml"),
    ]
    for setting in settings:
        if "digest=" in setting or "hostname=" in setting:
            command.extend(("--set-string", setting))
        else:
            command.extend(("--set", setting))
    return subprocess.run(command, check=False, capture_output=True, text=True)


def admitted_settings() -> tuple[str, ...]:
    return (
        "certificate.bootstrapEnabled=true",
        "certificate.stagingCertificateVerified=true",
        "activation.enabled=true",
        "activation.imageDigestLocked=true",
        "activation.pullSecretReady=true",
        "activation.serviceMonitorCRDReady=true",
        f"image.digest=sha256:{'a' * 64}",
    )


class Phase6StageASmokeContractTests(unittest.TestCase):
    def test_source_is_small_static_deterministic_and_passes_go_tests(self) -> None:
        go_mod = read_text(APP / "go.mod")
        source = read_text(APP / "main.go")
        self.assertNotIn("require ", go_mod)
        self.assertIn("go 1.26.0", go_mod)
        self.assertLess(len(source.encode("utf-8")), 12_000)
        for contract in (
            '"GET /"',
            '"GET /healthz"',
            '"GET /readyz"',
            '"GET /metrics"',
            'Marker = "platform_demo"',
            "platform_demo_requests_total",
            "platform_demo_build_info",
            "log.SetOutput(os.Stdout)",
        ):
            self.assertIn(contract, source)

        go = shutil.which("go")
        if go is None:
            raise unittest.SkipTest("Go is required for the source unit test")
        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
            scratch = pathlib.Path(directory)
            go_cache = scratch / "cache"
            go_tmp = scratch / "tmp"
            go_cache.mkdir()
            go_tmp.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "GOCACHE": str(go_cache),
                    "GOTMPDIR": str(go_tmp),
                    "GOTOOLCHAIN": "local",
                }
            )
            result = subprocess.run(
                [go, "test", "./..."],
                cwd=APP,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dockerfile_is_multistage_scratch_nonroot_and_fail_closed(self) -> None:
        dockerfile = read_text(APP / "Dockerfile")
        versions = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
        builder = versions["images"]["platform_demo_builder_reference"]
        quality_dockerfile = read_text(ROOT / "tooling" / "quality" / "Dockerfile")
        go_toolchain = versions["tool_delivery"]["go_toolchain"]
        self.assertEqual(go_toolchain["version"], "1.26.0")
        self.assertEqual(
            go_toolchain["source"],
            "https://go.dev/dl/go1.26.0.linux-amd64.tar.gz",
        )
        self.assertRegex(go_toolchain["linux_amd64_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("ARG GO_VERSION=1.26.0", quality_dockerfile)
        self.assertIn(
            f"ARG GO_LINUX_AMD64_SHA256={go_toolchain['linux_amd64_sha256']}",
            quality_dockerfile,
        )
        self.assertIn('"https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"', quality_dockerfile)
        self.assertIn(f"ARG GO_BUILDER_IMAGE={builder}", dockerfile)
        self.assertIn("FROM ${GO_BUILDER_IMAGE} AS build", dockerfile)
        self.assertIn('test "${#digest}" -eq 64', dockerfile)
        self.assertIn("*[!0-9a-f]*", dockerfile)
        self.assertIn("FROM scratch", dockerfile)
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn("CGO_ENABLED=0", dockerfile)
        self.assertIn("-trimpath -buildvcs=false", dockerfile)
        self.assertIn("-buildid=", dockerfile)
        self.assertNotRegex(dockerfile, r"(?i)(FROM|image:)\s+[^\n]*:latest")
        self.assertNotIn("apk add", dockerfile)

    def test_environment_values_are_inert_exact_and_share_one_digest_sentinel(
        self,
    ) -> None:
        digests = set()
        for environment, (namespace, replicas) in ENVIRONMENTS.items():
            with self.subTest(environment=environment):
                values = load_yaml(APP / f"values-{environment}.yaml")
                self.assertEqual(values["environment"], environment)
                self.assertEqual(values["namespace"], namespace)
                self.assertEqual(values["replicas"], replicas)
                self.assertFalse(values["activation"]["enabled"])
                self.assertFalse(values["certificate"]["bootstrapEnabled"])
                self.assertEqual(values["serviceAccountName"], "platform-demo")
                self.assertEqual(
                    values["imagePullSecretName"], "platform-demo-registry"
                )
                self.assertEqual(values["priorityClassName"], "platform-workload")
                self.assertEqual(
                    values["resources"],
                    {
                        "requests": {"cpu": "10m", "memory": "16Mi"},
                        "limits": {"cpu": "100m", "memory": "64Mi"},
                    },
                )
                digests.add(values["image"]["digest"])
                result = helm_template(environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(objects(result.stdout), [])
        self.assertEqual(digests, {"sha256:REQUIRED_STAGE_A_SMOKE_IMAGE_DIGEST"})

    def test_certificate_bootstrap_is_separate_from_workload_activation(self) -> None:
        result = helm_template("dev", "certificate.bootstrapEnabled=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)
        self.assertEqual(len(rendered), 2)
        self.assertEqual({item["kind"] for item in rendered}, {"Issuer", "Certificate"})
        certificate = next(item for item in rendered if item["kind"] == "Certificate")
        self.assertEqual(
            certificate["spec"]["dnsNames"],
            ["platform-dev.95-133-252-214.sslip.io"],
        )
        self.assertEqual(certificate["spec"]["secretName"], "platform-demo-staging-tls")

    def test_activation_rejects_missing_proofs_sentinel_zero_and_bad_namespace(
        self,
    ) -> None:
        no_proof = helm_template("dev", "activation.enabled=true")
        self.assertNotEqual(no_proof.returncode, 0)
        self.assertIn("staging certificate bootstrap", no_proof.stderr)

        sentinel = helm_template(
            "dev",
            "certificate.bootstrapEnabled=true",
            "certificate.stagingCertificateVerified=true",
            "activation.enabled=true",
            "activation.imageDigestLocked=true",
            "activation.pullSecretReady=true",
            "activation.serviceMonitorCRDReady=true",
        )
        self.assertNotEqual(sentinel.returncode, 0)
        self.assertIn("immutable sha256 digest", sentinel.stderr)

        zero = list(admitted_settings())
        zero[-1] = f"image.digest=sha256:{'0' * 64}"
        rejected_zero = helm_template("dev", *zero)
        self.assertNotEqual(rejected_zero.returncode, 0)
        self.assertIn("all-zero sentinel", rejected_zero.stderr)

        wrong_namespace = helm_template(
            "dev", *admitted_settings(), "namespace=demo-prod"
        )
        self.assertNotEqual(wrong_namespace.returncode, 0)
        self.assertIn("namespace does not match", wrong_namespace.stderr)

    def test_admitted_render_has_exact_workload_tls_metrics_and_security_contract(
        self,
    ) -> None:
        for environment, (namespace, replicas) in ENVIRONMENTS.items():
            with self.subTest(environment=environment):
                result = helm_template(environment, *admitted_settings())
                self.assertEqual(result.returncode, 0, result.stderr)
                rendered = objects(result.stdout)
                kinds = [item["kind"] for item in rendered]
                self.assertEqual(len(rendered), 10)
                self.assertEqual(kinds.count("Issuer"), 2)
                self.assertEqual(kinds.count("Certificate"), 2)
                self.assertEqual(kinds.count("NetworkPolicy"), 2)
                for forbidden in ("Secret", "Namespace", "ServiceAccount"):
                    self.assertNotIn(forbidden, kinds)

                deployment = next(
                    item for item in rendered if item["kind"] == "Deployment"
                )
                self.assertEqual(deployment["metadata"]["namespace"], namespace)
                self.assertEqual(deployment["spec"]["replicas"], replicas)
                pod = deployment["spec"]["template"]["spec"]
                self.assertEqual(pod["serviceAccountName"], "platform-demo")
                self.assertEqual(
                    pod["imagePullSecrets"], [{"name": "platform-demo-registry"}]
                )
                self.assertFalse(pod["automountServiceAccountToken"])
                container = pod["containers"][0]
                self.assertRegex(
                    container["image"],
                    r"^harbor\.[0-9-]+\.sslip\.io/platform-demo/platform-demo@sha256:[0-9a-f]{64}$",
                )
                self.assertNotIn(":latest", container["image"])
                self.assertEqual(
                    container["resources"],
                    {
                        "requests": {"cpu": "10m", "memory": "16Mi"},
                        "limits": {"cpu": "100m", "memory": "64Mi"},
                    },
                )
                security = container["securityContext"]
                self.assertTrue(security["readOnlyRootFilesystem"])
                self.assertTrue(security["runAsNonRoot"])
                self.assertFalse(security["allowPrivilegeEscalation"])
                self.assertEqual(security["capabilities"], {"drop": ["ALL"]})

                service = next(item for item in rendered if item["kind"] == "Service")
                self.assertEqual(service["spec"]["type"], "ClusterIP")
                ingress = next(item for item in rendered if item["kind"] == "Ingress")
                self.assertEqual(ingress["spec"]["ingressClassName"], "traefik")
                self.assertEqual(
                    ingress["spec"]["tls"][0]["secretName"], "platform-demo-tls"
                )
                monitor = next(
                    item for item in rendered if item["kind"] == "ServiceMonitor"
                )
                self.assertEqual(
                    monitor["metadata"]["labels"]["platform.verda-demo.io/monitor"],
                    "true",
                )
                self.assertEqual(monitor["spec"]["endpoints"][0]["path"], "/metrics")
                self.assertEqual(
                    monitor["spec"]["namespaceSelector"]["matchNames"], [namespace]
                )

    def test_network_policies_are_only_exact_ingress_exceptions(self) -> None:
        result = helm_template("dev", *admitted_settings())
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)
        policies = [item for item in rendered if item["kind"] == "NetworkPolicy"]
        self.assertEqual(
            {item["metadata"]["name"] for item in policies},
            {"platform-demo-traefik-ingress", "platform-demo-prometheus-ingress"},
        )
        for policy in policies:
            self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
            self.assertNotIn("egress", policy["spec"])
            self.assertEqual(
                policy["spec"]["ingress"][0]["ports"],
                [{"protocol": "TCP", "port": 8080}],
            )
        self.assertNotIn("0.0.0.0/0", result.stdout)
        self.assertNotIn("podSelector: {}", result.stdout)

    def test_values_schema_is_strict_and_host_environment_is_bound(self) -> None:
        schema = json.loads(read_text(CHART / "values.schema.json"))
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["activation"]["additionalProperties"])
        self.assertFalse(schema["properties"]["certificate"]["additionalProperties"])
        invalid = helm_template(
            "dev", *admitted_settings(), "hostname=platform-prod.192-0-2-10.sslip.io"
        )
        self.assertNotEqual(invalid.returncode, 0)

    def test_package_has_no_plaintext_secret_mutable_image_or_phase9_activation(
        self,
    ) -> None:
        text = "\n".join(
            read_text(path)
            for path in APP.rglob("*")
            if path.is_file() and path.name != "README.md"
        )
        for forbidden in (
            "kind: Secret",
            "stringData:",
            "dockerconfigjson:",
            "password:",
            "Bearer ",
            "curl -k",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIsNone(re.search(r"(?i)(image|FROM):?\s+[^\n]*:latest", text))
        self.assertFalse((APP / "go.sum").exists())
        self.assertTrue(
            (ROOT / "applications" / "platform-demo" / "Dockerfile").is_file()
        )


if __name__ == "__main__":
    unittest.main()
