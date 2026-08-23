#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "management-resize-transaction.sh"


class LinuxTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_only_read_only_verification_and_plan_are_exposed_initially(self) -> None:
        self.assertIn("case \"$action\"", self.source)
        self.assertIn("verify-state", self.source)
        self.assertIn("plan-node", self.source)
        self.assertIn('-var="ssh_public_key_path=$ssh_public_key"', self.source)
        self.assertIn('terraform-1.15.8', self.source)
        self.assertIn("assert-saved-plan", self.source)
        self.assertNotIn(' apply -input=false', self.source)
        self.assertNotIn("ansible-playbook", self.source)

    def test_linux_state_lease_and_cleanup_are_mandatory(self) -> None:
        self.assertIn("flock -n 9", self.source)
        self.assertIn("management.tfstate.gpg", self.source)
        self.assertIn("trap cleanup", self.source)
        self.assertIn("raw_values_recorded", self.source)

    def test_direct_host_invocation_refuses_on_non_linux(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT), "verify-state"], cwd=ROOT, check=False,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
