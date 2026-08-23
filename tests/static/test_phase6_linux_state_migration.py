#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "migrate-state-to-linux.ps1"


class LinuxStateMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_bridge_preserves_original_and_never_writes_plaintext(self) -> None:
        self.assertIn("original_dpapi_state_preserved = $true", self.source)
        self.assertIn("ProtectedData]::Unprotect", self.source)
        self.assertNotIn("WriteAllBytes($plaintextState", self.source)
        self.assertNotIn("Set-Content -LiteralPath $plaintextState", self.source)

    def test_linux_state_is_encrypted_and_round_trip_verified(self) -> None:
        self.assertIn("management.tfstate.gpg", self.source)
        self.assertIn("--encrypt", self.source)
        self.assertIn("--decrypt", self.source)
        self.assertIn("Linux encrypted-state round-trip verification failed", self.source)
        self.assertIn("chmod', '0600'", self.source)

    def test_secret_material_is_not_emitted(self) -> None:
        self.assertIn("raw_values_recorded = $false", self.source)
        self.assertNotIn("ConvertTo-Json -InputObject $state", self.source)
        self.assertNotIn("Write-Output $stateBytes", self.source)


if __name__ == "__main__":
    unittest.main()
