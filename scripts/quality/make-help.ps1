[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '[phase 2] target=help repository, quality, and Stage A infrastructure'
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
  make infra-init CLUSTER=management
                          Initialize encrypted external local state and a dedicated SSH key.
  make infra-plan CLUSTER=management
                          Revalidate the live catalog, save and assert a plan, and enforce cost.
  make infra-apply CLUSTER=management
                          Apply only the exact previously reviewed saved plan.
  make infra-repair-node-02-plan CLUSTER=management CONFIRM=--confirm
                          Assert a one-instance node-02 replacement plan; preserve its data volume.
  make infra-repair-node-02-apply CLUSTER=management CONFIRM=--confirm
                          Apply only the reviewed node-02 replacement plan with both safety guards.
  make inventory          Generate ignored machine-readable Ansible inventory from state.
  make verify-hosts CLUSTER=management
                          Verify attachments and SSH key access without host mutation.
  make infra-lifecycle-check CLUSTER=management
                          Prove full destroy is rejected and compute-only rollback is bounded.
  make cost-report        Reconcile provider-reported resources and hourly burn.

Targets owned by Phase 3 and later remain explicit non-mutating phase gates.
Use `make <target> CLUSTER=...` as documented in README.md.
'@ | Write-Host
