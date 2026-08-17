#!/usr/bin/env python3
"""Unit tests for strict Phase 3 runtime generation."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "host" / "prepare-runtime.py"
SPEC = importlib.util.spec_from_file_location("phase3_runtime", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def inventory() -> dict[str, object]:
    hosts = {}
    for index, name in enumerate(RUNTIME.EXPECTED_HOSTS, 1):
        hosts[name] = {
            "ansible_host": f"192.0.2.{index}",
            "data_volume_id": f"volume-{index}",
            "attached_device_id": f"volume-{index}",
            "data_volume_size_gib": 100,
        }
    return {"all": {"children": {"management_servers": {"hosts": hosts}}}}


class Phase3RuntimeTests(unittest.TestCase):
    def test_exact_runtime_uses_strict_host_keys(self) -> None:
        result = RUNTIME.build_runtime(inventory(), "platform-admin", "/key", "/known")
        hosts = result["all"]["children"]["management_servers"]["hosts"]
        self.assertEqual(len(hosts), 3)
        for host in hosts.values():
            self.assertIn("StrictHostKeyChecking=yes", host["ansible_ssh_common_args"])
            self.assertNotIn("accept-new", host["ansible_ssh_common_args"])

    def test_duplicate_endpoint_is_rejected(self) -> None:
        candidate = inventory()
        hosts = candidate["all"]["children"]["management_servers"]["hosts"]
        hosts["verda-mgmt-server-02"]["ansible_host"] = hosts["verda-mgmt-server-01"]["ansible_host"]
        with self.assertRaisesRegex(ValueError, "not unique"):
            RUNTIME.build_runtime(candidate, "root", "/key", "/known")

    def test_attachment_mismatch_is_rejected(self) -> None:
        candidate = inventory()
        hosts = candidate["all"]["children"]["management_servers"]["hosts"]
        hosts["verda-mgmt-server-03"]["attached_device_id"] = "different"
        with self.assertRaisesRegex(ValueError, "attachment identity"):
            RUNTIME.build_runtime(candidate, "root", "/key", "/known")

    def test_noncanonical_or_empty_cidr_is_rejected(self) -> None:
        for value in ("", "192.0.2.9/24", "2001:db8::/64"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RUNTIME.validate_cidrs(value)

    def test_cidrs_are_canonical_and_deduplicated(self) -> None:
        self.assertEqual(
            RUNTIME.validate_cidrs("198.51.100.7/32,198.51.100.7/32"),
            ["198.51.100.7/32"],
        )


if __name__ == "__main__":
    unittest.main()
