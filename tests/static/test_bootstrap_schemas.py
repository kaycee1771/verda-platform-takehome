#!/usr/bin/env python3
"""Unit tests for cache integrity and bounded schema-download retry behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from urllib.error import HTTPError

import jsonschema


SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "quality" / "bootstrap_schemas.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_schemas", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class BootstrapSchemaTests(unittest.TestCase):
    def test_cluster_fixtures_have_complete_locked_core_schema_coverage(self) -> None:
        lock = RUNTIME.yaml.safe_load(RUNTIME.LOCK.read_text(encoding="utf-8"))
        locked_core = {
            item["name"]: item["sha256"] for item in lock["kubernetes"]["files"]
        }
        required = {
            "daemonset-apps-v1.json",
            "service-v1.json",
            "networkpolicy-networking-v1.json",
            "ingress-networking-v1.json",
            "storageclass-storage-v1.json",
            "persistentvolumeclaim-v1.json",
            "resourcequota-v1.json",
            "limitrange-v1.json",
        }
        self.assertTrue(required.issubset(locked_core))
        for name in required:
            with self.subTest(schema=name):
                self.assertRegex(locked_core[name], r"^[0-9a-f]{64}$")

        validate = (
            pathlib.Path(__file__).parents[2] / "scripts" / "quality" / "validate.sh"
        ).read_text(encoding="utf-8")
        kubeconform_contract = validate.split("kubernetes_validate() {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn(
            "tests/cluster/phase4/network-smoke.yaml", kubeconform_contract
        )

    def test_every_materialized_schema_has_an_output_integrity_lock(self) -> None:
        lock = RUNTIME.yaml.safe_load(RUNTIME.LOCK.read_text(encoding="utf-8"))
        for item in lock["crds"]["materialized"]:
            with self.subTest(item=item["name"]):
                self.assertRegex(item["output_sha256"], r"^[0-9a-f]{64}$")

    def test_phase_five_custom_resources_have_exact_locked_schemas(self) -> None:
        lock = RUNTIME.yaml.safe_load(RUNTIME.LOCK.read_text(encoding="utf-8"))
        materialized = {item["name"]: item for item in lock["crds"]["materialized"]}
        required = {
            "argocd-appproject": None,
            "cert-manager-certificate": "cert-manager-helm-template-v1",
            "cert-manager-clusterissuer": "cert-manager-helm-template-v1",
            "cert-manager-issuer": "cert-manager-helm-template-v1",
            "longhorn-node": "longhorn-helm-labels-v1",
            "longhorn-setting": "longhorn-helm-labels-v1",
        }
        self.assertTrue(required.keys() <= materialized.keys())
        for name, normalization in required.items():
            with self.subTest(schema=name):
                item = materialized[name]
                self.assertEqual(item.get("normalization"), normalization)
                self.assertRegex(item["source_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(item["output_sha256"], r"^[0-9a-f]{64}$")

    def test_phase_six_custom_resources_have_exact_locked_schemas(self) -> None:
        lock = RUNTIME.yaml.safe_load(RUNTIME.LOCK.read_text(encoding="utf-8"))
        materialized = {item["name"]: item for item in lock["crds"]["materialized"]}
        required = {
            "cilium-network-policy": (
                "cilium.io",
                "v2",
                "CiliumNetworkPolicy",
            ),
            "kyverno-policyexception": ("kyverno.io", "v2", "PolicyException"),
            "velero-backupstoragelocation": (
                "velero.io",
                "v1",
                "BackupStorageLocation",
            ),
            "velero-volumesnapshotlocation": (
                "velero.io",
                "v1",
                "VolumeSnapshotLocation",
            ),
            "velero-schedule": ("velero.io", "v1", "Schedule"),
            "prometheus-operator-servicemonitor": (
                "monitoring.coreos.com",
                "v1",
                "ServiceMonitor",
            ),
            "prometheus-operator-podmonitor": (
                "monitoring.coreos.com",
                "v1",
                "PodMonitor",
            ),
            "prometheus-operator-prometheus": (
                "monitoring.coreos.com",
                "v1",
                "Prometheus",
            ),
            "prometheus-operator-alertmanager": (
                "monitoring.coreos.com",
                "v1",
                "Alertmanager",
            ),
        }
        self.assertTrue(required.keys() <= materialized.keys())
        for name, expected in required.items():
            with self.subTest(schema=name):
                item = materialized[name]
                self.assertEqual(
                    (item["group"], item["version"], item["kind"]), expected
                )
                self.assertRegex(item["source_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(item["output_sha256"], r"^[0-9a-f]{64}$")

        cilium = materialized["cilium-network-policy"]
        self.assertEqual(
            cilium["source"],
            "https://raw.githubusercontent.com/cilium/cilium/v1.19.6/"
            "pkg/k8s/apis/cilium.io/client/crds/v2/"
            "ciliumnetworkpolicies.yaml",
        )
        self.assertEqual(
            cilium["source_sha256"],
            "1b1738a904de1152c43078e6a873440aea100f30f10ce5ed4e8622524c13fa43",
        )
        self.assertEqual(
            cilium["output_sha256"],
            "917a0c28f44793cae8b147f2648104b261375e9a21883a504a9684f311fb8592",
        )

    def test_cache_is_used_only_when_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = pathlib.Path(directory) / "schema.json"
            candidate.write_bytes(b"expected")
            checksum = hashlib.sha256(b"expected").hexdigest()
            self.assertEqual(RUNTIME.cached_payload(candidate, checksum), b"expected")
            self.assertIsNone(RUNTIME.cached_payload(candidate, "0" * 64))

    def test_cilium_network_policy_schema_accepts_exact_fqdn_shape_only(self) -> None:
        schema_path = RUNTIME.CACHE / "ciliumnetworkpolicy-cilium-v2.json"
        self.assertTrue(schema_path.is_file(), "locked Cilium schema is not materialized")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {"name": "schema-contract", "namespace": "loki"},
            "spec": {
                "endpointSelector": {"matchLabels": {"component": "single-binary"}},
                "egress": [
                    {
                        "toFQDNs": [{"matchName": "objects.fin-03.verda.storage"}],
                        "toPorts": [
                            {"ports": [{"port": "443", "protocol": "TCP"}]}
                        ],
                    }
                ],
            },
        }
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(policy)
        policy["spec"]["egress"][0]["toFQDNs"] = "not-an-array"
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(policy)

    def test_http_429_honors_retry_after_then_verifies_checksum(self) -> None:
        payload = b"locked-schema"
        checksum = hashlib.sha256(payload).hexdigest()
        rate_limit = HTTPError(
            "https://example.invalid/schema",
            429,
            "Too Many Requests",
            {"Retry-After": "1"},
            None,
        )
        with (
            mock.patch.object(RUNTIME, "urlopen", side_effect=[rate_limit, FakeResponse(payload)]),
            mock.patch.object(RUNTIME.time, "sleep") as sleep,
        ):
            self.assertEqual(
                RUNTIME.download("https://example.invalid/schema", checksum), payload
            )
        sleep.assert_called_once_with(1)

    def test_github_token_uses_allowlisted_contents_api_only(self) -> None:
        source = (
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef/schema.yaml"
        )
        with mock.patch.dict(RUNTIME.os.environ, {"GITHUB_TOKEN": "ephemeral-token"}):
            request = RUNTIME.download_request(source)

        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/example/project/contents/schema.yaml"
            "?ref=0123456789abcdef",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer ephemeral-token")
        self.assertEqual(request.get_header("Accept"), "application/vnd.github.raw+json")
        self.assertEqual(
            request.get_header("X-github-api-version"), RUNTIME.GITHUB_API_VERSION
        )

    def test_github_token_is_not_forwarded_to_untrusted_hosts(self) -> None:
        source = "https://example.invalid/schema.yaml"
        with mock.patch.dict(RUNTIME.os.environ, {"GITHUB_TOKEN": "ephemeral-token"}):
            request = RUNTIME.download_request(source)

        self.assertEqual(request.full_url, source)
        self.assertIsNone(request.get_header("Authorization"))

    def test_unauthenticated_bootstrap_retains_locked_raw_url(self) -> None:
        source = (
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef/schema.yaml"
        )
        with mock.patch.dict(RUNTIME.os.environ, {}, clear=True):
            request = RUNTIME.download_request(source)

        self.assertEqual(request.full_url, source)
        self.assertIsNone(request.get_header("Authorization"))

    def test_retry_output_never_discloses_github_token(self) -> None:
        payload = b"locked-schema"
        checksum = hashlib.sha256(payload).hexdigest()
        rate_limit = HTTPError(
            "https://api.github.com/repos/example/project/contents/schema.yaml",
            429,
            "Too Many Requests",
            {"Retry-After": "1"},
            None,
        )
        output = io.StringIO()
        with (
            mock.patch.dict(RUNTIME.os.environ, {"GITHUB_TOKEN": "never-print-me"}),
            mock.patch.object(
                RUNTIME, "urlopen", side_effect=[rate_limit, FakeResponse(payload)]
            ),
            mock.patch.object(RUNTIME.time, "sleep"),
            redirect_stdout(output),
        ):
            self.assertEqual(
                RUNTIME.download(
                    "https://raw.githubusercontent.com/example/project/"
                    "0123456789abcdef/schema.yaml",
                    checksum,
                ),
                payload,
            )

        self.assertNotIn("never-print-me", output.getvalue())

    def test_download_rejects_wrong_checksum_after_success(self) -> None:
        with mock.patch.object(RUNTIME, "urlopen", return_value=FakeResponse(b"wrong")):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                RUNTIME.download("https://example.invalid/schema", "0" * 64)


if __name__ == "__main__":
    unittest.main()
