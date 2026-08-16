# ADR 0008: Use Harbor and Promote One Immutable Digest

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Supply-chain architecture
- **Blocking gates:** Exact Harbor/Trivy/Cosign versions remain pending Phase 1 lock review

## Context

The assignment explicitly requests Harbor or GitLab Registry with vulnerability scanning. Verda's managed registry may be operationally attractive, but it would not demonstrate the requested self-managed registry/scanner and artifact-governance path as directly.

## Decision

Use Harbor with Trivy, project-scoped robot identities, immutable tags, retention/GC, SBOM visibility, and Cosign-compatible signing. CI builds exactly once, discovers the SHA-256 digest, and promotes that digest through Git-reviewed dev → staging → production changes. Kubernetes never deploys a mutable tag alone.

## Alternatives considered

- **Verda managed registry:** rejected as the primary assignment registry; may remain a bootstrap mirror if later justified.
- **GitLab Registry:** valid but adds a broader platform and weaker alignment with the chosen focused architecture.
- **Rebuild per environment:** rejected because scanned/signed artifact identity would not be preserved.

## Consequences

- Harbor is a consequential stateful service and remains an application-level recovery concern.
- CI push and cluster pull identities must be separate and least privilege.
- Vulnerability/signature policy must prove both acceptance and denial without global weakening.

## Validation evidence

One commit must produce one digest, SBOM, scan result, signature/provenance, Harbor artifact, policy acceptance, and the identical deployed digest in all environments. Vulnerable, unsigned, tag-only, and external-registry negative tests must fail as designed.

## Production evolution

Use independent registry HA/database/object storage, organizational trust roots, keyless signing where appropriate, formal exception governance, and cross-site recovery.
