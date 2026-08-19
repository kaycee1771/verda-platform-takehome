#!/usr/bin/env python3
"""Prove the canonical Make interface is mapped to all 18 blueprint phases."""

from __future__ import annotations

import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[2]
PHASE_MAP = json.loads((ROOT / "config" / "phase-map.json").read_text(encoding="utf-8"))


class PhaseMapTests(unittest.TestCase):
    def test_all_eighteen_blueprint_phases_are_present(self) -> None:
        phases = PHASE_MAP["phases"]
        self.assertEqual([phase["id"] for phase in phases], list(range(18)))
        self.assertEqual(PHASE_MAP["active_phase"], 4)

    def test_every_make_target_has_one_owner_mapping(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        phony_block = makefile.split(".PHONY:", 1)[1].split("\n\n", 1)[0]
        make_targets = set(phony_block.replace("\\\n", " ").split())
        self.assertEqual(make_targets, set(PHASE_MAP["target_owners"]))

    def test_only_phase_four_cluster_targets_are_enabled(self) -> None:
        self.assertEqual(
            set(PHASE_MAP["enabled_phase_targets"]),
            {"cluster-bootstrap", "verify-cluster"},
        )
        self.assertEqual(
            set(PHASE_MAP["enabled_completed_phase_targets"]),
            {
                "infra-plan",
                "infra-lifecycle-check",
                "inventory",
                "configure",
                "verify-hosts",
            },
        )
        owners = PHASE_MAP["target_owners"]
        self.assertEqual(owners["configure"]["management"], 3)
        self.assertEqual(owners["verify-hosts"]["management"], 3)
        self.assertEqual(owners["cluster-bootstrap"]["management"], 4)
        self.assertEqual(owners["verify-cluster"]["management"], 4)
        self.assertEqual(owners["bootstrap-gitops"]["default"], 5)
        self.assertEqual(owners["stage-a-verify"]["default"], 6)

    def test_cluster_specific_owners_are_not_collapsed(self) -> None:
        owners = PHASE_MAP["target_owners"]
        for target in ("infra-init", "infra-plan", "infra-apply", "inventory"):
            self.assertEqual(owners[target], {"management": 2, "workload": 7})
        self.assertEqual(owners["configure"], {"management": 3, "workload": 7})
        self.assertEqual(owners["destroy"], {"management": 14, "workload": 14})

    def test_cloud_mutation_and_later_phases_remain_disabled(self) -> None:
        enabled = set(PHASE_MAP["enabled_phase_targets"]) | set(
            PHASE_MAP["enabled_completed_phase_targets"]
        )
        self.assertTrue(
            {
                "infra-apply",
                "infra-repair-node-02-plan",
                "infra-repair-node-02-apply",
                "bootstrap-gitops",
                "platform-status",
                "stage-a-verify",
                "destroy",
            }.isdisjoint(enabled)
        )


if __name__ == "__main__":
    unittest.main()
