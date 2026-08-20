#!/usr/bin/env python3
"""Behavioral negatives for the protected Phase 2 mutation boundary."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[2]
PHASE2 = ROOT / "scripts" / "infra" / "phase2.ps1"


@unittest.skipUnless(os.name == "nt", "Windows DPAPI/file-share behavior")
class Phase2MutationSafetyTests(unittest.TestCase):
    def pwsh(self, source: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", source],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_all_state_boundaries_share_one_os_lease_and_both_apply_paths_hold_plan_handles(self) -> None:
        source = PHASE2.read_text(encoding="utf-8")
        self.assertIn("$Target -in @('apply', 'repair-node-02-apply', 'destroy')", source)
        self.assertIn("$stateBoundaryLease = Enter-Phase2MutationLease -Paths $paths", source)
        self.assertIn("[Threading.Mutex]::new", source)
        self.assertNotIn("phase2-live-mutation.lock", source)
        self.assertIn("New-StagedReviewedPlan -Path $paths.PlanPath", source)
        self.assertIn("New-StagedReviewedPlan -Path $Paths.RepairPlanPath", source)
        self.assertEqual(source.count("Open-ReviewedPlanHandle -Path"), 1)
        self.assertGreaterEqual(source.count("Get-OpenPlanSha256 -Stream"), 3)
        self.assertIn("Exit-Phase2MutationLease -Lease $stateBoundaryLease", source)
        self.assertNotIn("$stream.SetLength(0)", source)
        self.assertIn("Assert-NoReparsePath -Path $Path -Label 'Reviewed Terraform saved plan'", source)
        self.assertIn("Phase 2 apply/destroy targets require Windows", source)

    def test_non_library_entrypoint_refuses_dot_source_without_exporting_functions(self) -> None:
        result = self.pwsh(rf"""
try {{ . '{PHASE2}' -Target phase6-resize-plan }} catch {{ $caught = $_.Exception.Message }}
if ([string]::IsNullOrWhiteSpace($caught)) {{ exit 91 }}
if (Get-Command Invoke-Terraform -ErrorAction SilentlyContinue) {{ exit 92 }}
if (Get-Command Invoke-Phase6ResizePlan -ErrorAction SilentlyContinue) {{ exit 93 }}
'dot-source-refused'
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dot-source-refused", result.stdout)

    def test_phase6_state_alias_matrix_preserves_every_asset_and_never_calls_terraform(self) -> None:
        for alias in ("private", "public", "known", "backup", "sealed_new", "hardlink"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                base, backup = root / "base", root / "backup"
                ssh = base / "ssh"
                state_dir = base / "terraform"
                ssh.mkdir(parents=True)
                state_dir.mkdir()
                backup.mkdir()
                private = ssh / "id_ed25519"
                public = ssh / "id_ed25519.pub"
                known = ssh / "known_hosts"
                backup_asset = backup / "management-protected.tfstate.dpapi"
                sealed_new = state_dir / "management.tfstate.dpapi.new"
                assets = {
                    "private": private,
                    "public": public,
                    "known": known,
                    "backup": backup_asset,
                    "sealed_new": sealed_new,
                }
                for name, path in assets.items():
                    path.write_text(f"sentinel-{name}", encoding="utf-8")
                expected_state = state_dir / "management.tfstate"
                if alias == "hardlink":
                    os.link(private, expected_state)
                    configured = expected_state
                else:
                    configured = assets[alias]
                result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{configured}'
$env:VERDA_CLIENT_ID = 'test-only'
$env:VERDA_CLIENT_SECRET = 'test-only'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'terraform must remain unreachable' }}
try {{
  & '{PHASE2}' -Target phase6-resize-plan -SavedPlan '{base / 'phase6' / 'plans' / 'node.tfplan'}' `
    -ExpectedStateLineageSha256 ('a' * 64) -ExpectedStateSerial 1 -OperationId ('b' * 64)
  exit 81
}} catch {{ if ($script:terraformCalled) {{ exit 82 }} }}
'state-alias-refused'
""")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("state-alias-refused", result.stdout)
                for name, path in assets.items():
                    self.assertEqual(path.read_text(encoding="utf-8"), f"sentinel-{name}")
                self.assertFalse(pathlib.Path(f"{configured}.dpapi").exists())

    def test_reviewed_plan_cannot_be_swapped_between_assertion_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state = base / "terraform" / "management.tfstate"
            plan = base / "terraform" / "management.tfplan"
            replacement = root / "replacement.tfplan"
            applied = root / "applied.txt"
            swap = root / "swap.txt"
            state.parent.mkdir(parents=True)
            backup.mkdir()
            state.write_text('{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}', encoding="utf-8")
            plan.write_text("REVIEWED-PLAN", encoding="utf-8")
            replacement.write_text("SWAPPED-PLAN", encoding="utf-8")
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_TF_STATE_PATH = '{state}'
$env:VERDA_CLIENT_ID = 'test-client'
$env:VERDA_CLIENT_SECRET = 'test-secret-value'
function verda {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  $joined = $Arguments -join ' '
  $global:LASTEXITCODE = 0
  if ($joined -match ' status$| status ') {{ '{{"financials":{{"balance":100}},"instances":{{"total":3}},"volumes":{{"total":6}}}}' }}
  elseif ($joined -match 'availability') {{ '{{"available":true,"spot":false}}' }}
  elseif ($joined -match 'instance-types') {{ '[{{"instance_type":"CPU.4V.16G","price_per_hour":0.0279}}]' }}
  elseif ($joined -match 'images') {{ '[{{"id":"77edfb23-bb0d-41cc-a191-dccae45d96fd","image_type":"ubuntu-24.04"}}]' }}
  else {{ exit 41 }}
}}
function python {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  if (($Arguments -join ' ') -match 'assert-plan.py') {{
    try {{
      Remove-Item -LiteralPath '{plan}' -Force -ErrorAction Stop
      New-Item -ItemType SymbolicLink -Path '{plan}' -Target '{replacement}' -ErrorAction Stop | Out-Null
      'SWAP-SUCCEEDED' | Set-Content '{swap}'
    }}
    catch {{ 'SWAP-BLOCKED' | Set-Content '{swap}' }}
  }}
  $global:LASTEXITCODE = 0
}}
function terraform {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  $joined = $Arguments -join ' '
  if ($joined -match ' apply ') {{ Get-Content -LiteralPath $Arguments[-1] -Raw | Set-Content -LiteralPath '{applied}' -NoNewline }}
  $global:LASTEXITCODE = 0
}}
& '{PHASE2}' -Target apply
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(swap.read_text(encoding="utf-8").strip(), "SWAP-SUCCEEDED")
            self.assertEqual(applied.read_text(encoding="utf-8"), "REVIEWED-PLAN")

    def test_hardlinked_lease_is_refused_without_mutating_asset_or_calling_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            locks, ssh, state_dir = base / "locks", base / "ssh", base / "terraform"
            locks.mkdir(parents=True)
            ssh.mkdir()
            state_dir.mkdir()
            backup.mkdir()
            private = ssh / "id_ed25519"
            private.write_text("protected-private-key-sentinel", encoding="utf-8")
            os.link(private, locks / "phase2-live-mutation.lock")
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'terraform must remain unreachable' }}
try {{ & '{PHASE2}' -Target init; exit 81 }}
catch {{ if ($script:terraformCalled) {{ exit 82 }} }}
'lease-hardlink-refused'
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("lease-hardlink-refused", result.stdout)
            self.assertEqual(private.read_text(encoding="utf-8"), "protected-private-key-sentinel")

    def test_reparse_lease_directory_is_refused_before_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup, redirected = root / "base", root / "backup", root / "redirected"
            base.mkdir()
            backup.mkdir()
            redirected.mkdir()
            locks = base / "locks"
            try:
                locks.symlink_to(redirected, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink creation is unavailable: {error}")
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$script:terraformCalled = $false
function terraform {{ $script:terraformCalled = $true; throw 'terraform must remain unreachable' }}
try {{ & '{PHASE2}' -Target init; exit 81 }}
catch {{ if ($script:terraformCalled) {{ exit 82 }} }}
'lease-reparse-refused'
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("lease-reparse-refused", result.stdout)
            self.assertEqual(list(redirected.iterdir()), [])
            locks.unlink()

    def test_state_boundary_lease_blocks_concurrent_open_and_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state = base / "terraform" / "management.tfstate"
            ready, release, second_called = root / "ready", root / "release", root / "second-called"
            state.parent.mkdir(parents=True)
            backup.mkdir()
            state.write_text('{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}', encoding="utf-8")
            first_source = rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_CLIENT_ID = 'test-client'
$env:VERDA_CLIENT_SECRET = 'test-secret-value'
function terraform {{
  New-Item -ItemType File -Force -Path '{ready}' | Out-Null
  $deadline = [DateTime]::UtcNow.AddSeconds(20)
  while (-not (Test-Path -LiteralPath '{release}')) {{
    if ([DateTime]::UtcNow -gt $deadline) {{ throw 'release timeout' }}
    Start-Sleep -Milliseconds 50
  }}
  $global:LASTEXITCODE = 0
}}
& '{PHASE2}' -Target init
"""
            first = subprocess.Popen(
                ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", first_source],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                for _ in range(200):
                    if ready.exists():
                        break
                    if first.poll() is not None:
                        stdout, stderr = first.communicate()
                        self.fail(stdout + stderr)
                    import time
                    time.sleep(0.05)
                self.assertTrue(ready.exists(), "first process never reached held-lease Terraform call")
                second = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
function terraform {{ New-Item -ItemType File -Force -Path '{second_called}' | Out-Null; $global:LASTEXITCODE = 0 }}
try {{ & '{PHASE2}' -Target init; exit 81 }} catch {{}}
'concurrent-boundary-refused'
""")
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("concurrent-boundary-refused", second.stdout)
                self.assertFalse(second_called.exists())
            finally:
                release.touch()
                stdout, stderr = first.communicate(timeout=30)
                self.assertEqual(first.returncode, 0, stdout + stderr)

    def test_reparse_plan_is_refused_before_semantic_review_or_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state = base / "terraform" / "management.tfstate"
            plan = base / "terraform" / "management.tfplan"
            target = root / "reviewed.tfplan"
            applied = root / "applied"
            reviewed = root / "reviewed"
            state.parent.mkdir(parents=True)
            backup.mkdir()
            state.write_text('{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}', encoding="utf-8")
            target.write_text("REVIEWED-PLAN", encoding="utf-8")
            try:
                plan.symlink_to(target)
            except OSError as error:
                self.skipTest(f"file symlink creation is unavailable: {error}")
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
$env:VERDA_CLIENT_ID = 'test-client'
$env:VERDA_CLIENT_SECRET = 'test-secret-value'
function verda {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  $joined = $Arguments -join ' '
  $global:LASTEXITCODE = 0
  if ($joined -match ' status$| status ') {{ '{{"financials":{{"balance":100}}}}' }}
  elseif ($joined -match 'availability') {{ '{{"available":true,"spot":false}}' }}
  elseif ($joined -match 'instance-types') {{ '[{{"instance_type":"CPU.4V.16G","price_per_hour":0.0279}}]' }}
  elseif ($joined -match 'images') {{ '[{{"id":"77edfb23-bb0d-41cc-a191-dccae45d96fd","image_type":"ubuntu-24.04"}}]' }}
  else {{ exit 41 }}
}}
function python {{ New-Item -ItemType File -Force -Path '{reviewed}' | Out-Null; $global:LASTEXITCODE = 0 }}
function terraform {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  if (($Arguments -join ' ') -match ' apply ') {{ New-Item -ItemType File -Force -Path '{applied}' | Out-Null }}
  $global:LASTEXITCODE = 0
}}
try {{ & '{PHASE2}' -Target apply; exit 81 }} catch {{}}
'reparse-plan-refused'
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("reparse-plan-refused", result.stdout)
            self.assertFalse(reviewed.exists())
            self.assertFalse(applied.exists())


if __name__ == "__main__":
    unittest.main()
