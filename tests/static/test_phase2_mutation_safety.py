#!/usr/bin/env python3
"""Behavioral negatives for the protected Phase 2 mutation boundary."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import threading
import time
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
        self.assertIn("FILE_FLAG_OPEN_REPARSE_POINT", source)
        self.assertGreaterEqual(source.count("[Phase2NativeFileIdentity]::VerifyDirectory"), 2)
        self.assertIn("ParentIdentity = $parentIdentity", source)
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

    def test_public_phase6_apply_is_absent_and_refuses_before_state_or_terraform(self) -> None:
        source = PHASE2.read_text(encoding="utf-8")
        self.assertNotIn("phase6-resize-apply", source)
        self.assertNotIn("Invoke-Phase6ResizeApply", source)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state = base / "terraform" / "management.tfstate"
            state.parent.mkdir(parents=True)
            backup.mkdir()
            state.write_text("state-must-not-be-opened", encoding="utf-8")
            marker = root / "terraform-called"
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
function terraform {{ New-Item -ItemType File -Force -Path '{marker}' | Out-Null }}
try {{ & '{PHASE2}' -Target phase6-resize-apply; exit 81 }} catch {{}}
if (Test-Path -LiteralPath '{marker}') {{ exit 82 }}
if ((Get-Content -Raw -LiteralPath '{state}') -ne 'state-must-not-be-opened') {{ exit 83 }}
'public-apply-absent-before-state-open'
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("public-apply-absent-before-state-open", result.stdout)
            self.assertFalse(marker.exists())

    def test_prepared_or_invalid_phase6_sentinel_blocks_generic_state_open(self) -> None:
        for state in ("PREPARED", "invalid-schema", "forged-completed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                base, backup = root / "base", root / "backup"
                control = base / "phase6-resize-control"
                state_path = base / "terraform" / "management.tfstate"
                control.mkdir(parents=True)
                state_path.parent.mkdir()
                backup.mkdir()
                state_path.write_text("state-must-remain-closed", encoding="utf-8")
                journal = control / f"phase6-resize-operation-{'1' * 64}.json"
                if state == "PREPARED":
                    journal.write_text(
                        '{"schema_version":1,"phase":6,"state":"PREPARED"}', encoding="utf-8"
                    )
                elif state == "invalid-schema":
                    journal.write_text(
                        '{"schema_version":99,"phase":6,"state":"COMPLETED"}', encoding="utf-8"
                    )
                else:
                    journal.write_text(
                        '{"schema_version":1,"phase":6,"state":"COMPLETED"}', encoding="utf-8"
                    )
                marker = root / "terraform-called"
                result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
function terraform {{ New-Item -ItemType File -Force -Path '{marker}' | Out-Null }}
try {{ & '{PHASE2}' -Target init; exit 81 }} catch {{}}
if (Test-Path -LiteralPath '{marker}') {{ exit 82 }}
if ((Get-Content -Raw -LiteralPath '{state_path}') -ne 'state-must-remain-closed') {{ exit 83 }}
'sentinel-refused-before-state-open'
""")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("sentinel-refused-before-state-open", result.stdout)
                self.assertFalse(marker.exists())

    def test_disabled_phase6_plan_refuses_tampered_plan_before_state_open_or_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            state_path = base / "terraform" / "management.tfstate"
            plan = base / "phase6" / "plans" / "tampered.tfplan"
            state_path.parent.mkdir(parents=True)
            plan.parent.mkdir(parents=True)
            backup.mkdir()
            state_path.write_text("state-must-remain-closed", encoding="utf-8")
            plan.write_text("unreviewed-plan-bytes", encoding="utf-8")
            marker = root / "terraform-called"
            result = self.pwsh(rf"""
$env:VERDA_TAKEHOME_CONFIG_DIR = '{base}'
$env:VERDA_TF_BACKUP_DIR = '{backup}'
function terraform {{ New-Item -ItemType File -Force -Path '{marker}' | Out-Null }}
try {{ & '{PHASE2}' -Target phase6-resize-plan -SavedPlan '{plan}'; exit 81 }} catch {{}}
if (Test-Path -LiteralPath '{marker}') {{ exit 82 }}
if ((Get-Content -Raw -LiteralPath '{state_path}') -ne 'state-must-remain-closed') {{ exit 83 }}
'disabled-plan-refused-before-state-open'
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("disabled-plan-refused-before-state-open", result.stdout)
            self.assertFalse(marker.exists())

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
            stage_swap = root / "stage-swap.txt"
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
    $planIndex = [Array]::IndexOf($Arguments, '--plan')
    $stagedPath = [string]$Arguments[$planIndex + 1]
    $stageParent = Split-Path -Parent $stagedPath
    try {{
      Move-Item -LiteralPath $stageParent -Destination '{root / 'moved-stage'}' -ErrorAction Stop
      'STAGING-SWAP-SUCCEEDED' | Set-Content '{stage_swap}'
    }} catch {{ 'STAGING-SWAP-BLOCKED' | Set-Content '{stage_swap}' }}
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
            self.assertEqual(stage_swap.read_text(encoding="utf-8").strip(), "STAGING-SWAP-BLOCKED")
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

    def test_transient_staging_directory_symlink_never_changes_applied_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, backup = root / "base", root / "backup"
            terraform_dir = base / "terraform"
            stage_dir = terraform_dir / "reviewed-plans"
            parked = root / "parked-stage"
            attacker = root / "attacker-stage"
            state = terraform_dir / "management.tfstate"
            plan = terraform_dir / "management.tfplan"
            applied = root / "applied.txt"
            terraform_dir.mkdir(parents=True)
            stage_dir.mkdir()
            backup.mkdir()
            attacker.mkdir()
            state.write_text('{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}', encoding="utf-8")
            plan.write_text("REVIEWED-PLAN", encoding="utf-8")
            stop = threading.Event()
            symlink_worked = threading.Event()

            def toggle() -> None:
                while not stop.is_set():
                    try:
                        if stage_dir.exists() and not stage_dir.is_symlink() and not parked.exists():
                            os.replace(stage_dir, parked)
                            stage_dir.symlink_to(attacker, target_is_directory=True)
                            symlink_worked.set()
                            for staged in parked.glob("reviewed-*.tfplan"):
                                (attacker / staged.name).write_text("ATTACKER-PLAN", encoding="utf-8")
                            stage_dir.unlink()
                            os.replace(parked, stage_dir)
                    except OSError:
                        pass
                    time.sleep(0.002)

            adversary = threading.Thread(target=toggle, daemon=True)
            adversary.start()
            try:
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
function python {{ $global:LASTEXITCODE = 0 }}
function terraform {{
  param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
  if (($Arguments -join ' ') -match ' apply ') {{
    Get-Content -LiteralPath $Arguments[-1] -Raw | Set-Content -LiteralPath '{applied}' -NoNewline
  }}
  $global:LASTEXITCODE = 0
}}
try {{ & '{PHASE2}' -Target apply }} catch {{ 'race-refused' }}
""")
            finally:
                stop.set()
                adversary.join(timeout=5)
                if stage_dir.is_symlink():
                    stage_dir.unlink()
                if parked.exists() and not stage_dir.exists():
                    os.replace(parked, stage_dir)
            self.assertTrue(symlink_worked.is_set(), "transient staging symlink adversary did not run")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if applied.exists():
                self.assertEqual(applied.read_text(encoding="utf-8"), "REVIEWED-PLAN")


if __name__ == "__main__":
    unittest.main()
