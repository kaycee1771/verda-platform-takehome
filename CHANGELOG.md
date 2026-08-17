# Changelog

All notable changes are recorded here. The project follows Keep a Changelog structure while phases
are under active development.

## Unreleased

### Added

- Phase 3 fail-closed host orchestrator, strict runtime generator, hardened-access bootstrap,
  baseline, storage, WireGuard, scoped nftables, diagnostics, serial reboot, external-scan, MTU,
  throughput, idempotency, and sanitized-report automation.
- Generated Phase 3 firewall port matrix, fixed overlay/MTU inputs, machine-tested implementation
  contract, ADR 0013, and complete `evidence/phase-3/` acceptance set.
- Bounded schema-download retry, content-addressed source caching, and locked materialized-CRD output
  hashes so an intact offline validation cache remains verifiable during upstream rate limiting.
- Canonical machine-readable ownership map for every Make target across all 18 blueprint phases,
  with only Phase 3 management-host configuration and hardened-host verification enabled.
- Initial-plan regression cases that reject absent, empty, or multiple persistent-volume
  attachments, plus final Phase 2 protected-main hosted-CI evidence.
- Phase 2 reusable Verda instance, volume, and three-node cluster modules plus the Stage A
  management root, native Terraform tests, strict plan assertions, cost gate, inventory generator,
  encrypted state wrapper, and guarded lifecycle commands.
- Two-part-confirmed node-02 recovery plan/apply targets with an exact one-instance replacement
  assertion that preserves the existing persistent data-volume attachment.
- ADR 0012 for provider image canonicalization and the current-user DPAPI state boundary.
- Phase 1 canonical repository topology and ownership contract.
- Pinned, containerized quality tool bootstrap shared by local development and CI.
- Positive validation, negative rejection tests, pre-commit hooks, schema cache, and secret scans.
- Documentation, runbook, failure-drill, restore, cost, and evidence templates.
- Hosted credential-free GitHub Actions validation with retained non-sensitive reports.
- Public-repository governance: real CODEOWNERS, protected `main`, required app-bound CI, squash-only
  pull requests, secret scanning, and push protection.

### Changed

- Made hosted schema bootstrap resistant to shared-runner raw-content rate limits by using the
  job-scoped read-only GitHub token only through allowlisted GitHub Contents API requests; local
  unauthenticated bootstrap and immutable checksum enforcement remain unchanged.
- Converted all three Ubuntu 24.04 Minimal hosts to named key-only administration, mounted each
  protected data volume by UUID, and established the peer-only 1420-byte WireGuard management mesh.
- Reserved a tested 1370-byte MTU for the future Cilium VXLAN layer while retaining the Phase 4 RKE2
  hard stop; extended ADR 0005/0006 with live Phase 3 outcomes and honest later-phase gates.
- Reconciled image-owned locale and host files, absent systemd units, nftables' `warn` grammar,
  stable mount detection, and scheduled reboot completion against observed Ubuntu behavior.
- Reconciled the Phase 2 closeout review: corrected stale README/summary/access status, fixed the
  initial-plan attachment assertion, aligned future commands to Phases 4–17, and blocked all cloud
  mutation and post-Phase-3 functionality.
- Activated only the Phase 2 Make targets while retaining hard stops for Phase 3 and later.
- Reconciled the provider's UUID-to-image-type readback defect without weakening the immutable live
  image mapping gate.
- Repaired the initial duplicate public-address allocation through the authorized compute/OS-only
  replacement, refreshed state outputs with a zero-resource plan, and corrected the remote hostname
  verifier's PowerShell argument construction.
- Replaced future-only CRD declarations with checksummed, release-specific schemas and fixtures for
  every Phase 1 custom API family.
- Made cache provenance, future-phase command guards, Aqua registry resolution, and local/CI
  validator configuration fail closed.
- Narrowed generated-file ignores after clean-clone testing and made the local validator image
  digest stable by excluding timestamped BuildKit attestations while retaining source-lock proof.
- Made generated-cache ownership portable across Windows and Linux bind mounts without granting
  world access, and upgraded the immutable `upload-artifact` pin to Node 24-native v7.0.1.
- Reconciled the `upload-artifact` version lock with the workflow SHA, added fail-closed validation
  for every remote GitHub Action reference, and refreshed Phase 1 evidence to the final protected
  `main` commit and hosted run.

### Security

- Applied rollback-protected SSH and firewall changes, proved a fresh strict session before
  lock-down, restricted SSH to the current exact `/32`, and verified root/password denial plus
  external closure of all future application and control-plane TCP ports.
- Generated WireGuard private keys only on their owning nodes and retrieved only public keys;
  committed Phase 3 evidence excludes raw endpoints, UUIDs, resource IDs, credentials, and private
  material.
- Recorded mandatory rotation of the time-bound Cloud API credential after its operator-controlled
  source image was visibly used for the bounded authenticated workflow.
- Created one time-bound project credential and a dedicated Ed25519 key outside Git; credential
  values remained process-only, and Terraform state is DPAPI-sealed with an independent encrypted
  backup.
- Whole-history and working-tree Gitleaks scans with 100 percent output redaction.
- CI permissions reduced to read-only contents; no cloud credentials are accepted by validation.
- Required status checks are bound to the GitHub Actions app identity; administrators cannot bypass
  the protected `main` rule, force-push, or delete the branch.

### Resolved issue

- Verda initially assigned the same public address to two independent VM records. The bounded
  server-02 replacement preserved its data volume; three unique endpoints, hostname-bound SSH, and
  final zero drift now pass.

## Phase 0 - 2026-08-16

### Added

- Assignment decomposition, architecture decisions, account/provider discovery, cost model,
  acceptance matrix, risk register, and Phase 0 evidence.
