#!/usr/bin/env python3
"""Unit tests for cache integrity and bounded schema-download retry behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError


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
    def test_every_materialized_schema_has_an_output_integrity_lock(self) -> None:
        lock = RUNTIME.yaml.safe_load(RUNTIME.LOCK.read_text(encoding="utf-8"))
        for item in lock["crds"]["materialized"]:
            with self.subTest(item=item["name"]):
                self.assertRegex(item["output_sha256"], r"^[0-9a-f]{64}$")

    def test_cache_is_used_only_when_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = pathlib.Path(directory) / "schema.json"
            candidate.write_bytes(b"expected")
            checksum = hashlib.sha256(b"expected").hexdigest()
            self.assertEqual(RUNTIME.cached_payload(candidate, checksum), b"expected")
            self.assertIsNone(RUNTIME.cached_payload(candidate, "0" * 64))

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

    def test_download_rejects_wrong_checksum_after_success(self) -> None:
        with mock.patch.object(RUNTIME, "urlopen", return_value=FakeResponse(b"wrong")):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                RUNTIME.download("https://example.invalid/schema", "0" * 64)


if __name__ == "__main__":
    unittest.main()
