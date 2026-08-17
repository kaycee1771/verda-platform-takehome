[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '[phase 3] target=help repository, quality, and hardened management hosts'
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
  make configure CLUSTER=management
                          Revalidate zero drift, then harden and network all hosts serially.
                          Requires process-only Verda credentials and PHASE3_ADMIN_CIDRS.
  make verify-hosts CLUSTER=management
                          Verify strict SSH, storage, time, WireGuard, MTU, and firewall controls.

Phase 2 cloud mutation is closed. RKE2 and every Phase 4+ target fail closed according to
config/phase-map.json. Use `make <target> CLUSTER=...` as documented in README.md.
'@ | Write-Host
