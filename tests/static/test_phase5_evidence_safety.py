#!/usr/bin/env python3
"""Keep committed Phase 5 evidence curated, bounded, and secret-free."""

from __future__ import annotations

import ipaddress
import json
import pathlib
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]
CONTRACT = ROOT / "tests" / "static" / "repository-contract.yaml"
MAX_EVIDENCE_BYTES = 128 * 1024

PHASE5_CLOSURE_FILES = {
    "evidence/phase-5/README.md",
    "evidence/phase-5/versions-and-compatibility.md",
    "evidence/phase-5/preflight-cluster-health.md",
    "evidence/phase-5/gitops-bootstrap.md",
    "evidence/phase-5/longhorn-reschedule.md",
    "evidence/phase-5/tls-access-and-boundary.md",
    "evidence/phase-5/capacity-before-after.md",
    "evidence/phase-5/repository-validation.md",
    "evidence/phase-5/hosted-ci.md",
    "evidence/phase-5/exit-gates.md",
    "evidence/phase-5/completion-report.md",
}

RAW_SUFFIXES = {
    ".cer",
    ".crt",
    ".key",
    ".pem",
    ".json",
    ".log",
    ".tgz",
    ".tar",
    ".gz",
    ".zip",
    ".kubeconfig",
}
RAW_KUBECONFIG_NAMES = {"admin.conf", "rke2.yaml"}
PEM_MATERIAL = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|"
    r"-----BEGIN OPENSSH " r"PRIVATE KEY-----|"
    r"-----BEGIN CERTIFICATE-----"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:[-*]\s+)?(?:export\s+)?(?P<name>"
    r"[A-Z0-9_]*(?:TOKEN|PASSWORD|CLIENT_SECRET|CLIENT_ID|ACCESS_KEY|SECRET_KEY)"
    r"[A-Z0-9_]*|"
    r"(?i:token|password|authorization|credential|secret|client[_-]?id|"
    r"client[_-]?secret|"
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
OPERATIONAL_ENDPOINT_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:[-*]\s+)?"
    r"(?:api[_-]?endpoint|endpoint|host(?:name)?|server|url)"
    r"\s*[:=]\s*(?P<value>[^\r\n]+)$"
)
SAFE_ENDPOINT_VALUE = re.compile(
    r"(?i)^[`'\"]?(?:\[?redacted\]?|<redacted>|omitted|external|none|null|"
    r"not[- ](?:recorded|stored|present|applicable))[`'\"]?$"
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
    """Return tracked plus non-ignored untracked Phase 5 evidence candidates."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "evidence/phase-5",
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
        violations.append("raw report/archive/key/certificate extension")
    if path.suffix.lower() != ".md":
        violations.append("Phase 5 evidence must be curated Markdown")
    if "kubeconfig" in name or name in RAW_KUBECONFIG_NAMES:
        violations.append("kubeconfig-like filename")
    return violations


def _looks_like_version(text: str, match: re.Match[str]) -> bool:
    prefix = text[max(0, match.start() - 24) : match.start()]
    suffix = text[match.end() : match.end() + 16]
    return bool(
        re.search(r"(?i)(?:\bversion\s+|(?<![a-z0-9])v)$", prefix)
        or re.match(r"[-+][0-9a-z]", suffix, flags=re.IGNORECASE)
    )


def _is_allowed_documented_ipv4(text: str, match: re.Match[str]) -> bool:
    if _looks_like_version(text, match):
        return True
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
    if PEM_MATERIAL.search(text):
        violations.append("private-key or certificate material")
    if AWS_ACCESS_KEY.search(text):
        violations.append("cloud access-key material")

    for match in SENSITIVE_ASSIGNMENT.finditer(text):
        if not SAFE_SENSITIVE_VALUE.fullmatch(match.group("value").strip()):
            violations.append(f"sensitive assignment: {match.group('name')}")

    for match in OPERATIONAL_ENDPOINT_ASSIGNMENT.finditer(text):
        if not SAFE_ENDPOINT_VALUE.fullmatch(match.group("value").strip()):
            violations.append("raw operational endpoint assignment")

    patterns = (
        (UUID, "raw UUID/resource identifier"),
        (MAC_ADDRESS, "raw MAC identifier"),
        (CONCRETE_SSLIP_NAME, "raw sslip.io endpoint"),
        (VERDA_OBJECT_ENDPOINT, "raw Verda object-storage endpoint"),
        (S3_LOCATION, "raw S3 location"),
    )
    for pattern, message in patterns:
        if pattern.search(text):
            violations.append(message)

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


def evidence_file_violations(path: pathlib.Path) -> list[str]:
    """Validate one evidence candidate without including any of its contents."""
    violations = filename_violations(path)
    payload = path.read_bytes()
    if len(payload) > MAX_EVIDENCE_BYTES:
        violations.append("evidence exceeds 128 KiB bound")
        return violations
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        violations.append("evidence is not UTF-8 text")
        return violations
    violations.extend(content_violations(text))
    return violations


class Phase5EvidenceSafetyTests(unittest.TestCase):
    def test_repository_contract_requires_complete_phase5_closeout_set(self) -> None:
        contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        required = set(contract["required_files"])
        self.assertTrue(PHASE5_CLOSURE_FILES.issubset(required))
        self.assertIn("tests/static/test_phase5_evidence_safety.py", required)

    def test_complete_phase5_closeout_set_exists(self) -> None:
        missing = [
            relative
            for relative in PHASE5_CLOSURE_FILES
            if not (ROOT / relative).is_file()
        ]
        self.assertEqual(sorted(missing), [])

    def test_repository_phase5_evidence_surface_is_curated(self) -> None:
        failures: list[str] = []
        for path in repository_evidence_surface():
            relative = path.relative_to(ROOT).as_posix()
            failures.extend(
                f"{relative}: {violation}"
                for violation in evidence_file_violations(path)
            )
        self.assertEqual(failures, [])

    def test_oversized_and_non_utf8_evidence_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = pathlib.Path(temporary_directory)
            oversized = temporary_root / "oversized.md"
            oversized.write_bytes(b"x" * (MAX_EVIDENCE_BYTES + 1))
            self.assertIn(
                "evidence exceeds 128 KiB bound",
                evidence_file_violations(oversized),
            )

            non_utf8 = temporary_root / "non-utf8.md"
            non_utf8.write_bytes(b"curated\xffevidence")
            self.assertIn(
                "evidence is not UTF-8 text",
                evidence_file_violations(non_utf8),
            )

    def test_raw_artifact_names_are_rejected(self) -> None:
        for name in (
            "runtime.json",
            "storage.log",
            "support.tgz",
            "management.kubeconfig",
            "admin.conf",
            "rke2.yaml",
            "raw.txt",
            "tls.crt",
            "tls.key",
        ):
            with self.subTest(name=name):
                self.assertTrue(filename_violations(pathlib.Path(name)))

    def test_secret_material_and_assignments_are_rejected(self) -> None:
        fixtures = (
            "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n",
            "-----BEGIN " + "CERTIFICATE-----\nnot-a-real-certificate\n",
            "PHASE5_ARGO_" + "TOKEN=not-a-real-but-sensitive-value\n",
            "client-key-" + "data: bm90LWEtcmVhbC1rZXk=\n",
            "Authoriz" + "ation: Bearer not-a-real-bearer-value\n",
            "AWS_ACCESS_KEY_" + "ID=AK" + "IA0000000000000000\n",
            "apiVersion: v1\nclusters:\ncontexts:\nusers:\n",
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
            "location=s3://example-bucket/object\n",
            "resource=01234567-89ab-4cde-8f01-23456789abcd\n",
            "link=00:11:22:33:44:55\n",
            "server=https://management.example.invalid:6443\n",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.strip()):
                self.assertTrue(content_violations(fixture))

    def test_sanitized_aggregate_currency_version_and_prose_are_allowed(self) -> None:
        fixture = """# Curated Phase 5 evidence

Argo CD version v3.3.2 and component version 1.2.3.4 were validated.
Nine of nine applications were Healthy and Synced; 6/6 replicas were ready.
The unchanged rate is $0.23165/hour and $5.55948/day.
The token, private key, credentials, certificate bodies, and kubeconfigs stayed
outside Git. No secret was printed. The endpoint was redacted.
The planned ranges are `10.42.0.0/16`, `10.43.0.0/16`, and `10.250.0.0/24`.
The documented cluster DNS service is `10.43.0.10`.
Official source: https://argo-cd.readthedocs.io/.
credential: redacted
server: redacted
secret_values_hashed: false
"""
        self.assertEqual(content_violations(fixture), [])


if __name__ == "__main__":
    unittest.main()
