#!/usr/bin/env python3
"""Offline contract tests for the Phase 6 Rancher desired state."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).parents[2]
RANCHER = ROOT / "platform" / "management" / "rancher"
ACCOUNT_SCRIPT = ROOT / "bootstrap" / "cluster-registration" / "register-rancher.sh"
CHART_CACHE = ROOT / ".local" / "chart-cache" / "rancher-2.14.3.tgz"
EXPECTED_ARCHIVE_SHA256 = (
    "65d4505a3547e7ee5179f14345377137e826541b4daf19c6a7575517f992daf6"
)
SAFE_HOSTNAME = "rancher.192-0-2-10.nip.io"


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: pathlib.Path) -> dict:
    return yaml.safe_load(read_text(path))


def rendered_objects(output: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]


def helm_template(*settings: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise unittest.SkipTest("helm is supplied by the pinned quality image")
    if not CHART_CACHE.is_file():
        raise unittest.SkipTest(
            "the coordinator has not materialized the Rancher chart cache"
        )
    if hashlib.sha256(CHART_CACHE.read_bytes()).hexdigest() != EXPECTED_ARCHIVE_SHA256:
        raise AssertionError(
            "cached Rancher chart checksum does not match the audited archive"
        )

    with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
        chart = pathlib.Path(directory) / "verda-rancher"
        shutil.copytree(RANCHER, chart)
        charts = chart / "charts"
        charts.mkdir()
        shutil.copy2(CHART_CACHE, charts / CHART_CACHE.name)
        command = [
            helm,
            "template",
            "rancher",
            str(chart),
            "--namespace",
            "cattle-system",
            "--kube-version",
            "1.35.7",
            "--set-string",
            f"rancher.hostname={SAFE_HOSTNAME}",
        ]
        for setting in settings:
            if setting.startswith("rancher.hostname=") or (
                setting.startswith("rancher.") and "tag=" in setting
            ):
                command.extend(("--set-string", setting))
            else:
                command.extend(("--set", setting))
        return subprocess.run(command, check=False, capture_output=True, text=True)


def admitted_settings() -> tuple[str, ...]:
    return (
        "rancher.enabled=true",
        "gates.stagingCertificateVerified=true",
        "gates.imageDigestsLocked=true",
        f"rancher.image.tag=v2.14.3@sha256:{'1' * 64}",
        f"rancher.auditLog.image.tag=15.6.24.2@sha256:{'2' * 64}",
        f"rancher.preUpgrade.image.tag=v0.7.1@sha256:{'3' * 64}",
        f"rancher.postDelete.image.tag=v0.7.1@sha256:{'3' * 64}",
    )


class Phase6RancherContractTests(unittest.TestCase):
    def test_wrapper_pins_exact_upstream_chart_and_kubernetes_line(self) -> None:
        chart = load_yaml(RANCHER / "Chart.yaml")
        self.assertEqual(chart["appVersion"], "v2.14.3")
        self.assertEqual(chart["kubeVersion"], ">=1.35.0-0 <1.36.0-0")
        self.assertEqual(
            chart["dependencies"],
            [
                {
                    "name": "rancher",
                    "version": "2.14.3",
                    "repository": "https://releases.rancher.com/server-charts/stable",
                    "condition": "rancher.enabled",
                }
            ],
        )

    def test_values_are_ha_strict_tls_bounded_and_destructive_hook_free(self) -> None:
        values = load_yaml(RANCHER / "values.yaml")
        self.assertTrue(values["rancher"]["enabled"])
        self.assertTrue(values["gates"]["stagingCertificateVerified"])
        self.assertTrue(values["gates"]["imageDigestsLocked"])
        self.assertEqual(values["rancher"]["replicas"], 1)
        self.assertEqual(values["rancher"]["antiAffinity"], "required")
        self.assertEqual(values["rancher"]["topologyKey"], "kubernetes.io/hostname")
        self.assertEqual(values["rancher"]["agentTLSMode"], "strict")
        self.assertEqual(values["rancher"]["bootstrapPassword"], "")
        self.assertEqual(values["rancher"]["priorityClassName"], "platform-critical")
        self.assertEqual(values["rancher"]["service"]["type"], "ClusterIP")
        self.assertEqual(values["rancher"]["ingress"]["ingressClassName"], "traefik")
        self.assertEqual(values["rancher"]["ingress"]["tls"]["source"], "secret")
        self.assertEqual(
            values["rancher"]["ingress"]["tls"]["secretName"],
            "tls-rancher-ingress",
        )
        self.assertTrue(values["rancher"]["auditLog"]["enabled"])
        self.assertEqual(values["rancher"]["auditLog"]["level"], 0)
        self.assertFalse(values["rancher"]["postDelete"]["enabled"])
        self.assertIn("requests", values["rancher"]["resources"])
        self.assertIn("limits", values["rancher"]["resources"])
        self.assertEqual(
            values["rancher"]["extraEnv"],
            [{"name": "CATTLE_PROMETHEUS_METRICS", "value": "true"}],
        )

    def test_initial_render_contains_only_staging_certificate_path(self) -> None:
        result = helm_template(
            "rancher.enabled=false",
            "gates.stagingCertificateVerified=false",
            "gates.imageDigestsLocked=false",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = rendered_objects(result.stdout)
        self.assertEqual({item["kind"] for item in objects}, {"Issuer", "Certificate"})
        self.assertEqual(len(objects), 2)
        issuer = next(item for item in objects if item["kind"] == "Issuer")
        certificate = next(item for item in objects if item["kind"] == "Certificate")
        self.assertEqual(issuer["metadata"]["name"], "letsencrypt-staging")
        self.assertEqual(
            issuer["spec"]["acme"]["server"],
            "https://acme-staging-v02.api.letsencrypt.org/directory",
        )
        self.assertEqual(certificate["metadata"]["name"], "rancher-staging")
        self.assertEqual(certificate["spec"]["dnsNames"], [SAFE_HOSTNAME])
        self.assertEqual(certificate["spec"]["secretName"], "rancher-staging-tls")

    def test_enablement_fails_closed_for_proof_and_each_digest(self) -> None:
        no_proof = helm_template(
            "rancher.enabled=true",
            "gates.stagingCertificateVerified=false",
        )
        self.assertNotEqual(no_proof.returncode, 0)
        self.assertIn("stagingCertificateVerified=true", no_proof.stderr)

        placeholders = helm_template(
            "rancher.enabled=true",
            "gates.stagingCertificateVerified=true",
            "gates.imageDigestsLocked=true",
            "rancher.image.tag=v2.14.3@sha256:REQUIRED_RANCHER_IMAGE_DIGEST",
        )
        self.assertNotEqual(placeholders.returncode, 0)
        self.assertIn("immutable sha256 digest", placeholders.stderr)

        all_zero = list(admitted_settings())
        all_zero[3] = f"rancher.image.tag=v2.14.3@sha256:{'0' * 64}"
        rejected = helm_template(*all_zero)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("all-zero sentinel", rejected.stderr)

    def test_admitted_render_has_one_pdb_tls_ingress_and_locked_images(self) -> None:
        result = helm_template(*admitted_settings())
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = rendered_objects(result.stdout)

        deployments = [item for item in objects if item["kind"] == "Deployment"]
        self.assertEqual(len(deployments), 1)
        deployment = deployments[0]
        self.assertEqual(deployment["metadata"]["name"], "rancher")
        self.assertEqual(deployment["spec"]["replicas"], 1)
        self.assertEqual(
            deployment["spec"]["strategy"]["rollingUpdate"],
            {"maxSurge": 1, "maxUnavailable": 0},
        )
        required = deployment["spec"]["template"]["spec"]["affinity"][
            "podAntiAffinity"
        ]["requiredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(len(required), 1)
        self.assertEqual(required[0]["topologyKey"], "kubernetes.io/hostname")

        images = [
            container["image"]
            for container in deployment["spec"]["template"]["spec"]["containers"]
        ]
        self.assertEqual(len(images), 2)
        for image in images:
            self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")
        rancher_container = next(
            container
            for container in deployment["spec"]["template"]["spec"]["containers"]
            if container["name"] == "rancher"
        )
        self.assertEqual(
            rancher_container["resources"]["requests"],
            {"cpu": "200m", "memory": "1Gi"},
        )
        self.assertIn(
            {"name": "CATTLE_AGENT_TLS_MODE", "value": "strict"},
            rancher_container["env"],
        )
        self.assertIn(
            {"name": "CATTLE_PROMETHEUS_METRICS", "value": "true"},
            rancher_container["env"],
        )

        pdbs = [item for item in objects if item["kind"] == "PodDisruptionBudget"]
        self.assertEqual(len(pdbs), 1)
        self.assertEqual(pdbs[0]["spec"]["minAvailable"], 2)
        self.assertEqual(pdbs[0]["spec"]["selector"]["matchLabels"], {"app": "rancher"})

        ingress = next(item for item in objects if item["kind"] == "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "traefik")
        self.assertEqual(ingress["spec"]["rules"][0]["host"], SAFE_HOSTNAME)
        self.assertEqual(
            ingress["spec"]["tls"],
            [{"hosts": [SAFE_HOSTNAME], "secretName": "tls-rancher-ingress"}],
        )

        certificates = {
            item["metadata"]["name"]: item
            for item in objects
            if item["kind"] == "Certificate"
        }
        self.assertEqual(set(certificates), {"rancher-staging", "rancher-production"})
        self.assertEqual(
            certificates["rancher-production"]["spec"]["secretName"],
            "tls-rancher-ingress",
        )

        policy = next(item for item in objects if item["kind"] == "NetworkPolicy")
        self.assertEqual(
            policy["spec"]["podSelector"]["matchLabels"], {"app": "rancher"}
        )
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])

        kinds = {item["kind"] for item in objects}
        self.assertNotIn("Secret", kinds)
        self.assertNotIn("Namespace", kinds)
        self.assertNotIn("ServiceMonitor", kinds)
        self.assertNotIn("LoadBalancer", result.stdout)
        self.assertNotIn("NodePort", result.stdout)

    def test_schema_is_strict_for_wrapper_values_and_rejects_non_nip_host(
        self,
    ) -> None:
        schema = json.loads(read_text(RANCHER / "values.schema.json"))
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["gates"]["additionalProperties"])
        self.assertFalse(schema["properties"]["certificate"]["additionalProperties"])
        self.assertRegex(
            SAFE_HOSTNAME,
            schema["properties"]["rancher"]["properties"]["hostname"]["pattern"],
        )

        invalid = helm_template(
            *admitted_settings(), "rancher.hostname=rancher.example.com"
        )
        self.assertNotEqual(invalid.returncode, 0)

    def test_owned_package_contains_no_plaintext_secret_or_live_credential(
        self,
    ) -> None:
        text = "\n".join(
            read_text(path)
            for path in RANCHER.rglob("*")
            if path.is_file() and path.name != "README.md"
        )
        for forbidden in (
            "kind: Secret",
            "stringData:",
            "bootstrapPassword: secret",
            "RANCHER_API_TOKEN",
            "Bearer ",
            "--insecure",
            "insecureSkip",
        ):
            self.assertNotIn(forbidden, text)

    def test_account_script_is_direct_kubeconfig_only_and_syntax_clean(self) -> None:
        script = read_text(ACCOUNT_SCRIPT)
        for required in (
            "set +x",
            "umask 077",
            "RANCHER_REVIEWER_CREDENTIAL_FILE",
            "/v1-public/login",
            "management.cattle.io.nodes",
            "apps.deployments",
            "auth can-i",
            "get secrets",
            "create pods/exec",
            "impersonate users",
            "--kubeconfig",
            "get --raw=/readyz",
        ):
            self.assertIn(required, script)
        for forbidden in (
            "RANCHER_API_TOKEN",
            "VERDA_CLIENT_SECRET",
            "password-hash",
            "kind: Secret",
            "globalRoleName: admin",
            "--insecure",
            "curl -k",
            "set -x",
            "not-implemented.sh",
        ):
            self.assertNotIn(forbidden, script)

        bash = shutil.which("bash")
        if bash is None:
            raise unittest.SkipTest("bash is supplied by the pinned quality image")
        syntax = subprocess.run(
            [bash, "-n", str(ACCOUNT_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        env = os.environ.copy()
        for name in tuple(env):
            if name.startswith("RANCHER_") or name == "KUBECONFIG":
                env.pop(name)
        no_authority = subprocess.run(
            [bash, str(ACCOUNT_SCRIPT), "verify"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(no_authority.returncode, 64)
        self.assertNotIn("password", no_authority.stdout.lower())

    def test_account_preflight_is_read_only_and_uses_direct_api(self) -> None:
        bash = shutil.which("bash")
        if bash is None or os.name == "nt":
            raise unittest.SkipTest(
                "behavioral shell test runs in the pinned Linux quality image"
            )

        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
            root = pathlib.Path(directory)
            binary = root / "bin"
            binary.mkdir()
            log = root / "kubectl.log"
            kubeconfig = root / "direct.kubeconfig"
            kubeconfig.write_text("protected test fixture\n", encoding="utf-8")
            kubeconfig.chmod(0o600)

            kubectl = binary / "kubectl"
            kubectl.write_text(
                """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >>"$FAKE_KUBECTL_LOG"
case "$*" in
  *"config view --minify"*) printf '%s' 'https://10.0.0.1:6443' ;;
  *"get --raw=/readyz"*) printf '%s' 'ok' ;;
  *"wait --for=condition=Established"*) ;;
  *"-n cattle-system rollout status deployment/rancher"*) ;;
  *"get namespace cattle-local-user-passwords"*) ;;
  *"get globalroles.management.cattle.io admin user"*) ;;
  *"get roletemplates.management.cattle.io read-only"*) printf '%s' 'cluster|true' ;;
  *"get users.management.cattle.io anonymous"*) exit 1 ;;
  *) printf 'unexpected fake kubectl call: %s\\n' "$*" >&2; exit 90 ;;
esac
""",
                encoding="utf-8",
            )
            kubectl.chmod(0o700)

            curl = binary / "curl"
            curl.write_text(
                """#!/usr/bin/env bash
set -eu
case "${!#}" in
  */ping) printf '%s' '200' ;;
  */v3/clusters|*/v3/users) printf '%s' '401' ;;
  *) exit 91 ;;
esac
""",
                encoding="utf-8",
            )
            curl.chmod(0o700)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{binary}{os.pathsep}{env['PATH']}",
                    "FAKE_KUBECTL_LOG": str(log),
                    "KUBECONFIG": str(kubeconfig),
                    "RANCHER_EXPECTED_HOSTNAME": SAFE_HOSTNAME,
                    "RANCHER_URL": f"https://{SAFE_HOSTNAME}",
                }
            )
            result = subprocess.run(
                [bash, str(ACCOUNT_SCRIPT), "preflight"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS preflight", result.stdout)
            commands = log.read_text(encoding="utf-8")
            self.assertIn("get --raw=/readyz", commands)
            self.assertNotRegex(commands, r"\b(create|apply|delete|patch|replace)\b")

    def test_account_script_mode_remains_executable(self) -> None:
        if os.name != "nt":
            self.assertTrue(ACCOUNT_SCRIPT.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
