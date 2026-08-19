from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "quality" / "cache_fingerprint.py"
SPEC = importlib.util.spec_from_file_location("cache_fingerprint", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_lock(path: Path, document: dict) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def minimal_document() -> dict:
    return {
        "terraform": {"version": "1.15.8"},
        "providers": {"verda": {"version": "1.1.2"}},
        "quality_tools": {"terraform": {"version": "1.15.8"}},
        "tool_delivery": {"quality_image": "quality:test"},
        "rke2": {"version": "v1.35.7+rke2r1"},
    }


class CacheFingerprintTests(unittest.TestCase):
    def test_future_phase_metadata_does_not_invalidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = minimal_document()
            second = copy.deepcopy(first)
            second["rke2"]["version"] = "v1.35.8+rke2r1"
            lock = root / "versions.lock.yaml"
            write_lock(lock, first)
            first_hash = MODULE.compute_fingerprint(root, lock)
            write_lock(lock, second)
            self.assertEqual(MODULE.compute_fingerprint(root, lock), first_hash)

    def test_quality_tool_change_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = minimal_document()
            lock = root / "versions.lock.yaml"
            write_lock(lock, document)
            first_hash = MODULE.compute_fingerprint(root, lock)
            document["quality_tools"]["terraform"]["version"] = "1.15.9"
            write_lock(lock, document)
            self.assertNotEqual(MODULE.compute_fingerprint(root, lock), first_hash)

    def test_provider_lock_change_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = minimal_document()
            lock = root / "versions.lock.yaml"
            write_lock(lock, document)
            provider_lock = root / "infra/terraform/env/.terraform.lock.hcl"
            provider_lock.parent.mkdir(parents=True)
            provider_lock.write_text("provider-a\n", encoding="utf-8")
            first_hash = MODULE.compute_fingerprint(root, lock)
            provider_lock.write_text("provider-b\n", encoding="utf-8")
            self.assertNotEqual(MODULE.compute_fingerprint(root, lock), first_hash)


if __name__ == "__main__":
    unittest.main()
