#!/usr/bin/env python3
"""Positive and negative tests for the bounded Phase 2 plan contracts."""

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


def initial_resources() -> list[dict[str, object]]:
    resources: list[dict[str, object]] = []
    for index in range(1, 4):
        node = instance(f"verda-mgmt-server-{index:02d}")
        node["os_volume"] = {
            "name": f"verda-mgmt-os-{index:02d}",
            "size": 80,
            "type": "NVMe",
        }
        node["existing_volumes"] = [f"data-volume-{index:02d}"]
        resources.append(
            {
                "address": f'module.management.module.node["{index:02d}"].verda_instance.this',
                "type": "verda_instance",
                "change": {"actions": ["create"], "after": node},
            }
        )
        resources.append(
            {
                "address": f'module.management.module.node["{index:02d}"].verda_volume.data',
                "type": "verda_volume",
                "change": {
                    "actions": ["create"],
                    "after": {
                        "name": f"verda-mgmt-data-{index:02d}",
                        "size": 100,
                        "type": "NVMe",
                        "location": "FIN-03",
                    },
                },
            }
        )
    resources.append(
        {
            "address": "verda_ssh_key.management",
            "type": "verda_ssh_key",
            "change": {"actions": ["create"], "after": {"name": "management"}},
        }
    )
    return resources


class InitialPlanTests(unittest.TestCase):
    def test_exact_initial_plan_passes(self) -> None:
        result = ASSERT_PLAN.assert_initial_plan(initial_resources())
        self.assertEqual(
            result["resource_counts"],
            {"verda_instance": 3, "verda_ssh_key": 1, "verda_volume": 3},
        )

    def test_missing_data_volume_attachment_is_rejected(self) -> None:
        candidate = copy.deepcopy(initial_resources())
        candidate[0]["change"]["after"]["existing_volumes"] = []
        with self.assertRaisesRegex(AssertionError, "exactly one external data volume"):
            ASSERT_PLAN.assert_initial_plan(candidate)

    def test_absent_data_volume_attachment_is_rejected(self) -> None:
        candidate = copy.deepcopy(initial_resources())
        del candidate[0]["change"]["after"]["existing_volumes"]
        with self.assertRaisesRegex(AssertionError, "exactly one external data volume"):
            ASSERT_PLAN.assert_initial_plan(candidate)

    def test_multiple_data_volume_attachments_are_rejected(self) -> None:
        candidate = copy.deepcopy(initial_resources())
        candidate[0]["change"]["after"]["existing_volumes"] = ["one", "two"]
        with self.assertRaisesRegex(AssertionError, "exactly one external data volume"):
            ASSERT_PLAN.assert_initial_plan(candidate)


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
