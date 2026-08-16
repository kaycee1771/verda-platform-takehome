# Phase 0 Validation Summary

- **Collected:** 2026-08-16
- **Workspace state:** New Git repository on `main`; no cloud resource created.
- **Validation command:** `pwsh -NoProfile -File scripts/phase0/validate.ps1`
- **Initial result:** 71 passed, 0 failed.
- **Hardened result:** 76 passed, 0 failed after PowerShell parsing and a static mutating-command guard were added.
- **Current result:** 80 passed, 0 failed after provider, discovery, and line-ending controls became required artifacts.
- **Credential preflight:** `VERDA_CLIENT_ID` and `VERDA_CLIENT_SECRET` were not present; no secret value was read or printed.
- **Account queries:** None.

## Observed toolchain

| Tool | Observation |
|---|---|
| PowerShell | 7.6.3 |
| Git | 2.50.1.windows.1 |
| kubectl | 1.36.1 from Docker Desktop |
| Terraform | 1.15.8, installed through Scoop |
| Verda CLI | 1.8.1, installed from Verda's official Scoop bucket |
| Ansible and platform validation tools | Not installed |

## Interpretation

The repository-side Phase 0 controls are operational. The Verda provider schema was exported without declaring or creating a resource. GATE-001 through GATE-004 remain blocked or partially blocked because authenticated account inventory, network behavior, and actual cost have not yet been collected. This is a controlled block against cloud mutation, not an architecture failure.

## Safeguard tests

- Account query without `-ConfirmReadOnly`: rejected before CLI execution.
- Output path outside the workspace: rejected before file creation.
- Provider export without a local IaC engine: rejected.
- Discovery script mutating-command scan: passed.
- No private-key marker or prohibited sensitive filename found.
