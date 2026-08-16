# Changelog

All notable changes are recorded here. The project follows Keep a Changelog structure while phases
are under active development.

## Unreleased

### Added

- Phase 1 canonical repository topology and ownership contract.
- Pinned, containerized quality tool bootstrap shared by local development and CI.
- Positive validation, negative rejection tests, pre-commit hooks, schema cache, and secret scans.
- Documentation, runbook, failure-drill, restore, cost, and evidence templates.
- Hosted credential-free GitHub Actions validation with retained non-sensitive reports.
- Public-repository governance: real CODEOWNERS, protected `main`, required app-bound CI, squash-only
  pull requests, secret scanning, and push protection.

### Changed

- Replaced future-only CRD declarations with checksummed, release-specific schemas and fixtures for
  every Phase 1 custom API family.
- Made cache provenance, future-phase command guards, Aqua registry resolution, and local/CI
  validator configuration fail closed.
- Narrowed generated-file ignores after clean-clone testing and made the local validator image
  digest stable by excluding timestamped BuildKit attestations while retaining source-lock proof.
- Made generated-cache ownership portable across Windows and Linux bind mounts without granting
  world access, and upgraded the immutable `upload-artifact` pin to Node 24-native v7.0.1.

### Security

- Whole-history and working-tree Gitleaks scans with 100 percent output redaction.
- CI permissions reduced to read-only contents; no cloud credentials are accepted by validation.
- Required status checks are bound to the GitHub Actions app identity; administrators cannot bypass
  the protected `main` rule, force-push, or delete the branch.

## Phase 0 - 2026-08-16

### Added

- Assignment decomposition, architecture decisions, account/provider discovery, cost model,
  acceptance matrix, risk register, and Phase 0 evidence.
