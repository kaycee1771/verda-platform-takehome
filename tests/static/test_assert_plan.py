#!/usr/bin/env python3
"""Negative and positive tests for the bounded Phase 2 recovery plan."""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "infra" / "assert-plan.py"
SPEC = importlib.util.spec_from_file_location("phase2_assert_plan", SCRIPT)
assert SPEC and SPEC.loader
ASSERT_PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSERT_PLAN)


def instance(hostname: str = "verda-mgmt-server-02") -> dict[str, object]:
    return {
        "hostname": hostname,
        "instance_type": "CPU.4V.16G",
        "image": "ubuntu-24.04",
        "location": "FIN-03",
        "is_spot": False,
        "os_volume": {"name": "verda-mgmt-os-02", "size": 80, "type": "NVMe"},
        "existing_volumes": ["preserved-data-volume"],
    }


def replacement() -> dict[str, object]:
    return {
        "address": ASSERT_PLAN.NODE_02_ADDRESS,
        "type": "verda_instance",
        "change": {
            "actions": ["delete", "create"],
            "before": instance(),
            "after": instance(),
        },
    }


class Node02ReplacementTests(unittest.TestCase):
    def test_exact_replacement_passes(self) -> None:
        result = ASSERT_PLAN.assert_node_02_replacement([replacement()])
        self.assertEqual(result["resource_counts"], {"verda_instance": 1})

    def test_extra_resource_is_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            ASSERT_PLAN.assert_node_02_replacement([replacement(), replacement()])

    def test_wrong_address_is_rejected(self) -> None:
        candidate = replacement()
        candidate["address"] = 'module.management.module.node["01"].verda_instance.this'
        with self.assertRaises(AssertionError):
            ASSERT_PLAN.assert_node_02_replacement([candidate])

    def test_non_replacement_action_is_rejected(self) -> None:
        candidate = replacement()
        candidate["change"]["actions"] = ["update"]
        with self.assertRaises(AssertionError):
            ASSERT_PLAN.assert_node_02_replacement([candidate])

    def test_changed_data_volume_is_rejected(self) -> None:
        candidate = copy.deepcopy(replacement())
        candidate["change"]["after"]["existing_volumes"] = ["different-volume"]
        with self.assertRaises(AssertionError):
            ASSERT_PLAN.assert_node_02_replacement([candidate])

    def test_changed_machine_contract_is_rejected(self) -> None:
        candidate = copy.deepcopy(replacement())
        candidate["change"]["after"]["image"] = "different-image"
        with self.assertRaises(AssertionError):
            ASSERT_PLAN.assert_node_02_replacement([candidate])


if __name__ == "__main__":
    unittest.main()
