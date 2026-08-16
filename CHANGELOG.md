# Changelog

All notable changes are recorded here. The project follows Keep a Changelog structure while phases
are under active development.

## Unreleased

### Added

- Phase 1 canonical repository topology and ownership contract.
- Pinned, containerized quality tool bootstrap shared by local development and CI.
- Positive validation, negative rejection tests, pre-commit hooks, schema cache, and secret scans.
- Documentation, runbook, failure-drill, restore, cost, and evidence templates.

### Changed

- Replaced future-only CRD declarations with checksummed, release-specific schemas and fixtures for
  every Phase 1 custom API family.
- Made cache provenance, future-phase command guards, Aqua registry resolution, and local/CI
  validator configuration fail closed.
- Narrowed generated-file ignores after clean-clone testing and made the local validator image
  digest stable by excluding timestamped BuildKit attestations while retaining source-lock proof.

### Security

- Whole-history and working-tree Gitleaks scans with 100 percent output redaction.
- CI permissions reduced to read-only contents; no cloud credentials are accepted by validation.

## Phase 0 - 2026-08-16

### Added

- Assignment decomposition, architecture decisions, account/provider discovery, cost model,
  acceptance matrix, risk register, and Phase 0 evidence.
