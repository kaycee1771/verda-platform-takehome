#!/usr/bin/env python3
"""Keep committed Phase 4 evidence curated, bounded, and secret-free."""

from __future__ import annotations

import ipaddress
import json
import pathlib
import re
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
EVIDENCE_ROOT = ROOT / "evidence" / "phase-4"
CONTRACT = ROOT / "tests" / "static" / "repository-contract.yaml"
MAX_EVIDENCE_BYTES = 128 * 1024

PHASE4_CLOSURE_FILES = {
    "evidence/phase-4/README.md",
    "evidence/phase-4/version-selection.md",
    "evidence/phase-4/cidr-design.md",
    "evidence/phase-4/repository-validation.md",
    "evidence/phase-4/live-preflight.md",
    "evidence/phase-4/object-storage-boundary.md",
    "evidence/phase-4/management-installation.md",
    "evidence/phase-4/common-config-parity.md",
    "evidence/phase-4/management-nodes.txt",
    "evidence/phase-4/management-etcd-health.txt",
    "evidence/phase-4/management-cilium-connectivity.txt",
    "evidence/phase-4/management-networking.md",
    "evidence/phase-4/management-firewall-scan.md",
    "evidence/phase-4/management-snapshots.md",
    "evidence/phase-4/management-cis-assessment.md",
    "evidence/phase-4/management-node-failure.md",
    "evidence/phase-4/management-endpoint-failure.md",
    "evidence/phase-4/management-support-bundle.md",
    "evidence/phase-4/stability-and-idempotency.md",
    "evidence/phase-4/manual-object-storage-exception.md",
    "evidence/phase-4/deviations-and-recovery.md",
    "evidence/phase-4/hosted-ci.md",
    "evidence/phase-4/exit-gates.md",
}

RAW_SUFFIXES = {
    ".json",
    ".log",
    ".tgz",
    ".tar",
    ".gz",
    ".zip",
    ".kubeconfig",
}
RAW_KUBECONFIG_NAMES = {"admin.conf", "rke2.yaml"}
PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|"
    r"-----BEGIN OPENSSH PRIVATE " r"KEY-----"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:export\s+)?(?P<name>"
    r"[A-Z0-9_]*(?:TOKEN|PASSWORD|CLIENT_SECRET|CLIENT_ID|ACCESS_KEY|SECRET_KEY)"
    r"[A-Z0-9_]*|"
    r"(?i:token|password|authorization|secret|client[_-]?id|client[_-]?secret|"
    r"access[_-]?key(?:[_-]?id)?|secret[_-]?key|session[_-]?token|"
    r"client[_-]?key[_-]?data|client[_-]?certificate[_-]?data|"
    r"certificate[_-]?authority[_-]?data)"
    r")\s*[:=]\s*(?P<value>[^\r\n]*)$"
)
SAFE_SENSITIVE_VALUE = re.compile(
    r"(?i)^[`'\"]?(?:"
    r"|\[?redacted\]?|<redacted>|omitted|external|process-only|none|null|"
    r"not[- ](?:recorded|stored|present|applicable)|"
    r"supplied[- ]out[- ]of[- ]band|false|true"
    r")[`'\"]?$"
)
UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
MAC_ADDRESS = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
CONCRETE_SSLIP_NAME = re.compile(r"(?i)\b[a-z0-9.-]+\.sslip\.io\b")
VERDA_OBJECT_ENDPOINT = re.compile(r"(?i)\bobjects\.[a-z0-9-]+\.verda\.storage\b")
S3_LOCATION = re.compile(r"(?i)\bs3://[^\s)`]+")
AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


def repository_evidence_surface() -> list[pathlib.Path]:
    """Return the Git-controlled surface, including untracked non-ignored candidates."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "evidence/phase-4",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def filename_violations(path: pathlib.Path) -> list[str]:
    name = path.name.lower()
    violations: list[str] = []
    if path.suffix.lower() in RAW_SUFFIXES:
        violations.append("raw report/archive extension")
    if "kubeconfig" in name or name in RAW_KUBECONFIG_NAMES:
        violations.append("kubeconfig-like filename")
    return violations


def _is_allowed_documented_ipv4(text: str, match: re.Match[str]) -> bool:
    address = ipaddress.ip_address(match.group(0))
    if address == ipaddress.ip_address("10.43.0.10"):
        return True
    suffix = text[match.end() : match.end() + 4]
    cidr = re.match(r"/(\d{1,2})", suffix)
    if cidr is None:
        return address.is_loopback or address.is_unspecified
    network = ipaddress.ip_network(f"{address}/{cidr.group(1)}", strict=False)
    return (
        address == network.network_address
        and network.prefixlen < network.max_prefixlen
        and not address.is_global
    )


def content_violations(text: str) -> list[str]:
    violations: list[str] = []
    if PEM_PRIVATE_KEY.search(text):
        violations.append("private-key material")
    if AWS_ACCESS_KEY.search(text):
        violations.append("cloud access-key material")

    for match in SENSITIVE_ASSIGNMENT.finditer(text):
        if not SAFE_SENSITIVE_VALUE.fullmatch(match.group("value").strip()):
            violations.append(f"sensitive assignment: {match.group('name')}")

    if UUID.search(text):
        violations.append("raw UUID/resource identifier")
    if MAC_ADDRESS.search(text):
        violations.append("raw MAC identifier")
    if CONCRETE_SSLIP_NAME.search(text):
        violations.append("raw sslip.io endpoint")
    if VERDA_OBJECT_ENDPOINT.search(text):
        violations.append("raw Verda object-storage endpoint")
    if S3_LOCATION.search(text):
        violations.append("raw S3 location")

    for match in IPV4.finditer(text):
        try:
            allowed = _is_allowed_documented_ipv4(text, match)
        except ValueError:
            violations.append("malformed IPv4-like identifier")
            continue
        if not allowed:
            violations.append("raw IPv4 endpoint")

    kubeconfig_fields = (
        re.search(r"(?m)^\s*apiVersion:\s*v1\s*$", text),
        re.search(r"(?m)^\s*clusters:\s*$", text),
        re.search(r"(?m)^\s*contexts:\s*$", text),
        re.search(r"(?m)^\s*users:\s*$", text),
    )
    if all(kubeconfig_fields):
        violations.append("raw kubeconfig payload")

    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            violations.append("raw JSON payload in curated evidence")
    return violations


class Phase4EvidenceSafetyTests(unittest.TestCase):
    def test_repository_contract_requires_complete_phase4_closeout_set(self) -> None:
        contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        self.assertTrue(PHASE4_CLOSURE_FILES.issubset(set(contract["required_files"])))

    def test_repository_phase4_evidence_surface_is_curated(self) -> None:
        failures: list[str] = []
        for path in repository_evidence_surface():
            relative = path.relative_to(ROOT).as_posix()
            failures.extend(
                f"{relative}: {violation}" for violation in filename_violations(path)
            )
            payload = path.read_bytes()
            if len(payload) > MAX_EVIDENCE_BYTES:
                failures.append(f"{relative}: evidence exceeds 128 KiB bound")
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                failures.append(f"{relative}: evidence is not UTF-8 text")
                continue
            failures.extend(
                f"{relative}: {violation}" for violation in content_violations(text)
            )
        self.assertEqual(failures, [])

    def test_raw_artifact_names_are_rejected(self) -> None:
        for name in (
            "management-verification.json",
            "snapshot.log",
            "verda-rke2-support.tgz",
            "management-primary.kubeconfig",
            "admin.conf",
            "rke2.yaml",
        ):
            with self.subTest(name=name):
                self.assertTrue(filename_violations(pathlib.Path(name)))

    def test_secret_material_and_assignments_are_rejected(self) -> None:
        fixtures = (
            "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n",
            "PHASE4_RKE2_" + "TOKEN=not-a-real-but-secret-value\n",
            "client-key-" + "data: bm90LWEtcmVhbC1rZXk=\n",
            "Authoriz" + "ation: Bearer not-a-real-bearer-value\n",
            "AWS_ACCESS_KEY_" + "ID=AK" + "IA0000000000000000\n",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.splitlines()[0]):
                self.assertTrue(content_violations(fixture))

    def test_operational_endpoint_identifiers_are_rejected(self) -> None:
        fixtures = (
            "node=203.0.113.42\n",
            "node=10.250.0.11\n",
            "api=203-0-113-42.sslip.io\n",
            "endpoint=objects.fin-03.verda.storage\n",
            "location=s3://example-bucket/snapshot\n",
            "resource=01234567-89ab-4cde-8f01-23456789abcd\n",
            "link=00:11:22:33:44:55\n",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.strip()):
                self.assertTrue(content_violations(fixture))

    def test_security_prose_and_public_configuration_are_allowed(self) -> None:
        fixture = """# Security evidence

The token, private key, credentials, and kubeconfigs stayed outside Git.
No secret was printed. The access key was supplied out of band.
The planned ranges are `10.42.0.0/16`, `10.43.0.0/16`, and `10.250.0.0/24`.
The documented cluster DNS service is `10.43.0.10`.
Official source: https://docs.rke2.io/security/hardening_guide.
secret_values_hashed: false
"""
        self.assertEqual(content_violations(fixture), [])


if __name__ == "__main__":
    unittest.main()
