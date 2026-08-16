[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '[phase 1] target=help repository and quality system'
@'
Canonical targets
  make bootstrap-tools    Build the pinned local quality image and warm immutable caches.
  make install-hooks      Install the lightweight repository pre-commit wrapper.
  make validate           Run every Phase 1 positive quality gate offline.
  make validate-negative  Prove malformed Terraform, Kubernetes, alert, and key inputs are rejected.
  make pre-commit         Execute all configured pre-commit hooks in the pinned image.
  make secret-scan        Scan the working tree and complete Git history with redaction.
  make ci                 Run the same positive and negative suites used by GitHub Actions.
  make discover           Run the Phase 0 non-mutating local Verda preflight.

Future targets are present to preserve the command contract. Before their owning phase is
implemented they stop with a phase-gate error; they never silently succeed or mutate cloud state.
Use `make <target> CLUSTER=...` as documented in README.md.
'@ | Write-Host
