#!/usr/bin/env python3
"""Offline contract tests for the Phase 6 Harbor and Trivy baseline."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).parents[2]
HARBOR = ROOT / "platform" / "management" / "harbor"
SERVICE = HARBOR / "service"
SECRETS = HARBOR / "secrets"
POSTGRESQL = HARBOR / "postgresql"
BOOTSTRAP = HARBOR / "bootstrap-private-projects.sh"
CHART_CACHE = ROOT / ".local" / "chart-cache" / "harbor-1.19.2.tgz"
EXPECTED_ARCHIVE_SHA256 = (
    "36d8eeb41b4df1aeff18c9af7709110a2fac2194b491d37957822b3359cd5e9a"
)
SAFE_HOSTNAME = "harbor.192-0-2-10.sslip.io"


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: pathlib.Path) -> dict:
    return yaml.safe_load(read_text(path))


def objects(output: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]


def helm_template(
    chart: pathlib.Path, *settings: str
) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise unittest.SkipTest("helm is supplied by the pinned quality image")

    with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
        rendered_chart = pathlib.Path(directory) / chart.name
        shutil.copytree(chart, rendered_chart)
        if chart == SERVICE:
            if not CHART_CACHE.is_file():
                raise unittest.SkipTest(
                    "the coordinator has not materialized Harbor 1.19.2"
                )
            digest = hashlib.sha256(CHART_CACHE.read_bytes()).hexdigest()
            if digest != EXPECTED_ARCHIVE_SHA256:
                raise AssertionError(
                    "cached Harbor chart checksum is not the audited archive"
                )
            charts = rendered_chart / "charts"
            charts.mkdir()
            shutil.copy2(CHART_CACHE, charts / CHART_CACHE.name)

        command = [
            helm,
            "template",
            "harbor" if chart == SERVICE else chart.name,
            str(rendered_chart),
            "--namespace",
            "harbor",
            "--kube-version",
            "1.35.7",
        ]
        for setting in settings:
            if "tag=" in setting or "Ciphertext=" in setting or "hostname=" in setting:
                command.extend(("--set-string", setting))
            else:
                command.extend(("--set", setting))
        return subprocess.run(command, check=False, capture_output=True, text=True)


def admitted_service_settings() -> tuple[str, ...]:
    return (
        "harbor.enabled=true",
        "gates.stagingCertificateVerified=true",
        "gates.sealedSecretsReady=true",
        "gates.postgresqlReady=true",
        "gates.capacityAdmitted=true",
        "gates.imageDigestsLocked=true",
        f"harbor.expose.ingress.hosts.core={SAFE_HOSTNAME}",
        f"harbor.externalURL=https://{SAFE_HOSTNAME}",
        f"harbor.portal.image.tag=v2.15.2@sha256:{'1' * 64}",
        f"harbor.core.image.tag=v2.15.2@sha256:{'2' * 64}",
        f"harbor.jobservice.image.tag=v2.15.2@sha256:{'3' * 64}",
        f"harbor.registry.registry.image.tag=v2.15.2@sha256:{'4' * 64}",
        f"harbor.registry.controller.image.tag=v2.15.2@sha256:{'5' * 64}",
        f"harbor.trivy.image.tag=v2.15.2@sha256:{'6' * 64}",
        f"harbor.redis.internal.image.tag=v2.15.2@sha256:{'7' * 64}",
        f"harbor.exporter.image.tag=v2.15.2@sha256:{'8' * 64}",
    )


class Phase6HarborContractTests(unittest.TestCase):
    def test_wrapper_pins_the_checksum_locked_harbor_chart(self) -> None:
        chart = load_yaml(SERVICE / "Chart.yaml")
        self.assertEqual(chart["appVersion"], "2.15.2")
        self.assertEqual(chart["kubeVersion"], ">=1.35.0-0 <1.36.0-0")
        self.assertEqual(
            chart["dependencies"],
            [
                {
                    "name": "harbor",
                    "version": "1.19.2",
                    "repository": "https://helm.goharbor.io",
                    "condition": "harbor.enabled",
                }
            ],
        )
        if CHART_CACHE.is_file():
            self.assertEqual(
                hashlib.sha256(CHART_CACHE.read_bytes()).hexdigest(),
                EXPECTED_ARCHIVE_SHA256,
            )

    def test_initial_service_render_is_staging_certificate_only(self) -> None:
        result = helm_template(
            SERVICE,
            f"harbor.expose.ingress.hosts.core={SAFE_HOSTNAME}",
            f"harbor.externalURL=https://{SAFE_HOSTNAME}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)
        self.assertEqual({item["kind"] for item in rendered}, {"Issuer", "Certificate"})
        self.assertEqual(len(rendered), 2)
        certificate = next(item for item in rendered if item["kind"] == "Certificate")
        self.assertEqual(certificate["spec"]["dnsNames"], [SAFE_HOSTNAME])
        self.assertEqual(certificate["spec"]["secretName"], "harbor-staging-tls")

    def test_service_admission_rejects_missing_proof_placeholders_and_zero_digest(
        self,
    ) -> None:
        no_proof = helm_template(SERVICE, "harbor.enabled=true")
        self.assertNotEqual(no_proof.returncode, 0)
        self.assertIn("stagingCertificateVerified=true", no_proof.stderr)

        placeholders = helm_template(
            SERVICE,
            "harbor.enabled=true",
            "gates.stagingCertificateVerified=true",
            "gates.sealedSecretsReady=true",
            "gates.postgresqlReady=true",
            "gates.capacityAdmitted=true",
            "gates.imageDigestsLocked=true",
            "harbor.core.image.tag=v2.15.2@sha256:REQUIRED_HARBOR_CORE_DIGEST",
        )
        self.assertNotEqual(placeholders.returncode, 0)
        self.assertIn("immutable sha256 digest", placeholders.stderr)

        settings = list(admitted_service_settings())
        settings[8] = f"harbor.portal.image.tag=v2.15.2@sha256:{'0' * 64}"
        zero = helm_template(SERVICE, *settings)
        self.assertNotEqual(zero.returncode, 0)
        self.assertIn("all-zero sentinel", zero.stderr)

    def test_admitted_harbor_render_is_tls_private_persistent_and_digest_only(
        self,
    ) -> None:
        result = helm_template(SERVICE, *admitted_service_settings())
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)

        workloads = [
            item
            for item in rendered
            if item.get("kind") in {"Deployment", "StatefulSet", "Job"}
        ]
        images = []
        for workload in workloads:
            pod_spec = workload["spec"].get("template", {}).get("spec", {})
            for field in ("initContainers", "containers"):
                images.extend(
                    container["image"] for container in pod_spec.get(field, [])
                )
        self.assertEqual(len(images), 8)
        for image in images:
            self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")
        self.assertNotIn("goharbor/harbor-db", "\n".join(images))
        self.assertNotIn("goharbor/nginx", "\n".join(images))

        ingresses = [item for item in rendered if item["kind"] == "Ingress"]
        self.assertEqual(len(ingresses), 1)
        ingress = ingresses[0]
        self.assertEqual(ingress["spec"]["ingressClassName"], "traefik")
        self.assertEqual(ingress["spec"]["rules"][0]["host"], SAFE_HOSTNAME)
        self.assertEqual(
            ingress["spec"]["tls"],
            [{"hosts": [SAFE_HOSTNAME], "secretName": "tls-harbor-ingress"}],
        )

        pvc_sizes = set()
        for item in rendered:
            if item["kind"] == "PersistentVolumeClaim":
                pvc_sizes.add(item["spec"]["resources"]["requests"]["storage"])
            for claim in item.get("spec", {}).get("volumeClaimTemplates", []):
                pvc_sizes.add(claim["spec"]["resources"]["requests"]["storage"])
        self.assertEqual(pvc_sizes, {"2Gi", "10Gi", "20Gi"})
        self.assertNotIn("PodDisruptionBudget", {item["kind"] for item in rendered})
        for item in rendered:
            if item["kind"] in {"Deployment", "StatefulSet"}:
                for container in item["spec"]["template"]["spec"].get("containers", []):
                    self.assertIn("requests", container["resources"])
                    self.assertIn("limits", container["resources"])

        secrets = [item for item in rendered if item["kind"] == "Secret"]
        forbidden_decoded = {
            "Harbor12345",
            "changeit",
            "harbor_registry_password",
            "not-a-secure-key",
        }
        for secret in secrets:
            for encoded in (secret.get("data") or {}).values():
                if encoded:
                    import base64

                    decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                    self.assertNotIn(decoded, forbidden_decoded)

    def test_network_contract_is_default_deny_and_component_scoped(self) -> None:
        result = helm_template(SERVICE, *admitted_service_settings())
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)
        policies = {
            item["metadata"]["name"]: item
            for item in rendered
            if item["kind"] in {"NetworkPolicy", "CiliumNetworkPolicy"}
        }
        self.assertIn("harbor-default-deny", policies)
        self.assertEqual(
            policies["harbor-default-deny"]["spec"]["policyTypes"],
            ["Ingress", "Egress"],
        )
        self.assertIn("harbor-traefik-ingress", policies)
        self.assertNotIn("harbor-metrics-ingress", policies)
        self.assertIn("harbor-trivy-database-egress", policies)
        fqdn_policy = policies["harbor-trivy-database-egress"]
        names = {
            entry["matchName"]
            for rule in fqdn_policy["spec"]["egress"]
            for entry in rule.get("toFQDNs", [])
        }
        self.assertEqual(
            names,
            {"mirror.gcr.io", "ghcr.io", "pkg-containers.githubusercontent.com"},
        )
        self.assertNotIn("0.0.0.0/0", result.stdout)

    def test_target_monitor_selects_exact_metrics_services_from_admitted_render(
        self,
    ) -> None:
        result = helm_template(SERVICE, *admitted_service_settings())
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = objects(result.stdout)
        target_objects = objects(
            read_text(
                ROOT
                / "platform/management/monitoring/targets/harbor/monitoring.yaml"
            )
        )
        monitor = next(item for item in target_objects if item["kind"] == "ServiceMonitor")
        selector = monitor["spec"]["selector"]
        self.assertEqual(
            selector,
            {
                "matchLabels": {
                    "app.kubernetes.io/instance": "harbor",
                    "app.kubernetes.io/name": "harbor",
                }
            },
        )
        endpoint_port = monitor["spec"]["endpoints"][0]["port"]
        selected = set()
        for service in (item for item in rendered if item["kind"] == "Service"):
            labels = service["metadata"].get("labels", {})
            if not all(
                labels.get(key) == value
                for key, value in selector["matchLabels"].items()
            ):
                continue
            if any(
                port.get("name") == endpoint_port
                for port in service["spec"].get("ports", [])
            ):
                selected.add(service["metadata"]["name"])
        self.assertEqual(
            selected,
            {"harbor-core", "harbor-exporter", "harbor-jobservice", "harbor-registry"},
        )

    def test_sealed_secret_boundary_is_inert_and_rejects_sentinels(self) -> None:
        inert = helm_template(SECRETS)
        self.assertEqual(inert.returncode, 0, inert.stderr)
        self.assertEqual(objects(inert.stdout), [])

        rejected = helm_template(
            SECRETS,
            "enabled=true",
            "gates.ciphertextsLocked=true",
            "ciphertexts.adminPassword=not-a-kubeseal-ciphertext",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("real kubeseal ciphertext", rejected.stderr)

        fake = "Ag" + "A" * 90
        settings = ["enabled=true", "gates.ciphertextsLocked=true"]
        for name in load_yaml(SECRETS / "values.yaml")["ciphertexts"]:
            settings.append(f"ciphertexts.{name}Ciphertext={fake}")
        # The helper above deliberately recognizes any setting containing
        # Ciphertext as a string. Correct the actual value key names here.
        settings = ["enabled=true", "gates.ciphertextsLocked=true"] + [
            f"ciphertexts.{name}={fake}"
            for name in load_yaml(SECRETS / "values.yaml")["ciphertexts"]
        ]
        admitted = helm_template(SECRETS, *settings)
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        rendered = objects(admitted.stdout)
        self.assertEqual(len(rendered), 7)
        self.assertEqual({item["kind"] for item in rendered}, {"SealedSecret"})
        self.assertNotIn("kind: Secret", admitted.stdout)
        self.assertNotIn("stringData:", admitted.stdout)

    def test_postgresql_is_separate_singleton_persistent_and_fail_closed(self) -> None:
        inert = helm_template(POSTGRESQL)
        self.assertEqual(inert.returncode, 0, inert.stderr)
        self.assertEqual(objects(inert.stdout), [])

        rejected = helm_template(
            POSTGRESQL,
            "enabled=true",
            "gates.sealedCredentialsReady=true",
            "gates.imageDigestLocked=true",
            "image.tag=15.10-bookworm@sha256:REQUIRED_POSTGRESQL_IMAGE_DIGEST",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("immutable sha256 digest", rejected.stderr)

        admitted = helm_template(
            POSTGRESQL,
            "enabled=true",
            "gates.sealedCredentialsReady=true",
            "gates.imageDigestLocked=true",
            f"image.tag=15.10-bookworm@sha256:{'9' * 64}",
        )
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        rendered = objects(admitted.stdout)
        statefulset = next(item for item in rendered if item["kind"] == "StatefulSet")
        self.assertEqual(statefulset["spec"]["replicas"], 1)
        self.assertEqual(statefulset["spec"]["updateStrategy"]["type"], "RollingUpdate")
        self.assertRegex(
            statefulset["spec"]["template"]["spec"]["containers"][0]["image"],
            r"postgres:15\.10-bookworm@sha256:[0-9a-f]{64}$",
        )
        claim = statefulset["spec"]["volumeClaimTemplates"][0]
        self.assertEqual(claim["spec"]["storageClassName"], "longhorn-critical")
        self.assertEqual(claim["spec"]["resources"]["requests"]["storage"], "8Gi")
        self.assertNotIn("PodDisruptionBudget", {item["kind"] for item in rendered})
        self.assertNotIn("Secret", {item["kind"] for item in rendered})
        policy = next(item for item in rendered if item["kind"] == "NetworkPolicy")
        self.assertEqual(policy["spec"]["egress"], [])

    def test_no_plaintext_secret_or_unlocked_active_image_is_committed(self) -> None:
        package_text = "\n".join(
            read_text(path)
            for path in HARBOR.rglob("*")
            if path.is_file() and path.name != "README.md"
        )
        for forbidden in (
            "Harbor12345",
            "changeit",
            "harbor_registry_password",
            "not-a-secure-key",
            "kind: Secret\n",
            "stringData:",
            "--insecure",
            "curl -k",
            "Bearer ",
        ):
            self.assertNotIn(forbidden, package_text)
        self.assertNotIn("REQUIRED_HARBOR_CORE_DIGEST", package_text)
        self.assertNotIn("REQUIRED_POSTGRESQL_IMAGE_DIGEST", package_text)
        self.assertIn("REQUIRED_SEALED_CIPHERTEXT", package_text)

    def test_project_bootstrap_is_guarded_private_guest_only_and_syntax_clean(
        self,
    ) -> None:
        script = read_text(BOOTSTRAP)
        for required in (
            "set +x",
            "umask 077",
            "HARBOR_MUTATION_APPROVED",
            "HARBOR_MUTATION_SCOPE",
            '"public":"false"',
            '"auto_scan":"true"',
            '"auto_sbom_generation":"true"',
            '"role_id":3',
            "/api/v2.0/health",
            "/blobs/uploads/",
            "--proto '=https'",
            "--tlsv1.2",
        ):
            self.assertIn(required, script)
        for forbidden in ("curl -k", "--insecure", "set -x", 'role_id":1'):
            self.assertNotIn(forbidden, script)

        bash = shutil.which("bash")
        if bash is None:
            raise unittest.SkipTest("bash is supplied by the pinned quality image")
        syntax = subprocess.run(
            [bash, "-n", str(BOOTSTRAP)], capture_output=True, text=True, check=False
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_project_bootstrap_preflight_is_read_only(self) -> None:
        bash = shutil.which("bash")
        if bash is None or os.name == "nt":
            raise unittest.SkipTest(
                "behavioral shell test runs in the Linux quality image"
            )
        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
            root = pathlib.Path(directory)
            binary = root / "bin"
            binary.mkdir()
            log = root / "curl.log"
            curl = binary / "curl"
            curl.write_text(
                """#!/usr/bin/env bash
set -eu
output=''
method='GET'
url=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --request) method="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
printf '%s %s\\n' "$method" "$url" >>"$FAKE_CURL_LOG"
case "$url" in
  */api/v2.0/health) printf '%s' '{"status":"healthy"}' >"$output"; printf 200 ;;
  */api/v2.0/projects/platform-demo) printf '%s' '{}' >"$output"; printf 404 ;;
  */v2/platform-demo/blobs/uploads/) printf '%s' '{}' >"$output"; printf 401 ;;
  *) exit 90 ;;
esac
""",
                encoding="utf-8",
            )
            curl.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{binary}{os.pathsep}{env['PATH']}",
                    "FAKE_CURL_LOG": str(log),
                    "HARBOR_URL": f"https://{SAFE_HOSTNAME}",
                }
            )
            for name in tuple(env):
                if name.startswith("HARBOR_") and name not in {
                    "HARBOR_URL",
                }:
                    env.pop(name)
            result = subprocess.run(
                [bash, str(BOOTSTRAP), "preflight"],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS preflight", result.stdout)
            calls = log.read_text(encoding="utf-8")
            self.assertNotRegex(calls, r"\b(PUT|DELETE|PATCH)\b")
            self.assertNotIn("POST https://harbor.192-0-2-10.sslip.io/api", calls)


if __name__ == "__main__":
    unittest.main()
