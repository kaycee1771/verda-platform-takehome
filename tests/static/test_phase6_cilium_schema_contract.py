#!/usr/bin/env python3
"""Strict offline schema coverage for Phase 6 CiliumNetworkPolicy objects."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
import unittest

import jsonschema
import yaml

import test_phase6_harbor_contract as harbor_contract


ROOT = pathlib.Path(__file__).parents[2]
SCHEMA_LOCK = ROOT / "schemas" / "schema-sources.lock.yaml"
VERSIONS_LOCK = ROOT / "versions.lock.yaml"
SCHEMA = ROOT / ".local" / "schema-cache" / "ciliumnetworkpolicy-cilium-v2.json"
ALLOY_VALUES = ROOT / "observability" / "alloy" / "values.yaml"

EXPECTED_SOURCE = (
    "https://raw.githubusercontent.com/cilium/cilium/v1.19.6/"
    "pkg/k8s/apis/cilium.io/client/crds/v2/ciliumnetworkpolicies.yaml"
)
EXPECTED_SOURCE_SHA256 = (
    "1b1738a904de1152c43078e6a873440aea100f30f10ce5ed4e8622524c13fa43"
)
EXPECTED_OUTPUT_SHA256 = (
    "917a0c28f44793cae8b147f2648104b261375e9a21883a504a9684f311fb8592"
)


def load_yaml(path: pathlib.Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AssertionError(f"{path} must contain a YAML mapping")
    return document


def cilium_policy(objects: list[dict], source: pathlib.Path | str) -> dict:
    policies = [
        item
        for item in objects
        if item.get("apiVersion") == "cilium.io/v2"
        and item.get("kind") == "CiliumNetworkPolicy"
    ]
    if len(policies) != 1:
        raise AssertionError(
            f"{source} must produce exactly one CiliumNetworkPolicy; "
            f"found {len(policies)}"
        )
    return policies[0]


def values_policy(path: pathlib.Path) -> dict:
    values = load_yaml(path)
    extra_objects = values.get("extraObjects")
    if not isinstance(extra_objects, list):
        raise AssertionError(f"{path} must define extraObjects as a list")
    return cilium_policy(extra_objects, path)


class Phase6CiliumSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SCHEMA.is_file():
            raise AssertionError(
                "the locked CiliumNetworkPolicy schema is not materialized; "
                "run make bootstrap-tools"
            )
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def test_materialized_schema_is_checksum_locked_to_cilium_v1_19_6(self) -> None:
        versions = load_yaml(VERSIONS_LOCK)
        self.assertEqual(versions["rke2"]["cilium_version"], "v1.19.6")

        schema_lock = load_yaml(SCHEMA_LOCK)
        entries = {
            item["name"]: item for item in schema_lock["crds"]["materialized"]
        }
        locked = entries["cilium-network-policy"]
        self.assertEqual(
            (locked["group"], locked["version"], locked["kind"]),
            ("cilium.io", "v2", "CiliumNetworkPolicy"),
        )
        self.assertEqual(locked["source"], EXPECTED_SOURCE)
        self.assertEqual(locked["source_sha256"], EXPECTED_SOURCE_SHA256)
        self.assertEqual(locked["output"], SCHEMA.name)
        self.assertEqual(locked["output_sha256"], EXPECTED_OUTPUT_SHA256)
        self.assertEqual(
            hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
            EXPECTED_OUTPUT_SHA256,
        )

    def test_current_alloy_policy_validates_strictly(self) -> None:
        self.validator.validate(values_policy(ALLOY_VALUES))

    def test_current_admitted_harbor_policy_validates_strictly(self) -> None:
        self.assertIsNotNone(
            shutil.which("helm"),
            "pinned Helm is required to validate the admitted Harbor policy",
        )
        self.assertTrue(
            harbor_contract.CHART_CACHE.is_file(),
            "the checksum-audited Harbor chart cache must be materialized",
        )
        rendered = harbor_contract.helm_template(
            harbor_contract.SERVICE,
            *harbor_contract.admitted_service_settings(),
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        policy = cilium_policy(harbor_contract.objects(rendered.stdout), "Harbor render")
        self.validator.validate(policy)

    def test_malformed_real_alloy_policy_is_rejected(self) -> None:
        malformed = copy.deepcopy(values_policy(ALLOY_VALUES))
        malformed["metadata"]["name"] = "malformed-real-derived-policy"
        malformed["spec"]["egress"][0]["toFQDNs"] = "not-an-array"
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(malformed)


if __name__ == "__main__":
    unittest.main()
