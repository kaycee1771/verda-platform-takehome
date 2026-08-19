# ADR 0011: Use Layered Recovery and Require Restore Proof

- **Status:** Accepted for the Phase 4 management-snapshot boundary; restore proof remains phase-gated
- **Date:** 2026-08-16
- **Owners:** Recovery architecture
- **Blocking gates:** GATE-008 and live restore evidence

## Context

Git, Terraform state, etcd, Kubernetes objects, persistent volumes, component databases, and sealing keys have different recovery semantics. A successful backup job does not prove recoverability.

## Decision

Use Git for declarative state, protected Terraform state/backup for infrastructure lifecycle, RKE2 etcd snapshots for cluster state, Velero for Kubernetes resources/filesystem backups, Longhorn snapshot/backup for volume recovery, component-specific exports where consistency requires them, and an encrypted off-repository Sealed Secrets key backup. Use separate credentials/buckets/prefixes in a genuinely off-cluster S3-compatible target. The current project now has Verda object-storage entitlement and passed the Phase 4 compatibility boundary, so management etcd snapshots use that off-cluster target through the documented manual provider-gap exception. ADR-0006's external S3 fallback remains the portability path.

## Alternatives considered

- **Only etcd snapshots:** insufficient for infrastructure lifecycle and independent volume/application recovery.
- **Only Velero:** insufficient for Terraform, sealing keys, and some component consistency requirements.
- **Only Longhorn replicas/snapshots:** shares failure domains and is not cluster/application recovery.

## Consequences

- Recovery has multiple runbooks and retention/credential dependencies.
- Recovery objectives must be stated per data class, not as one vague platform number.
- Verda Terraform provider 1.1.2 cannot own the bucket or credential lifecycle; inventory,
  rotation, and teardown therefore remain explicit operator responsibilities.
- Phase 4 proves scheduled and on-demand compressed recovery points in local and off-cluster
  location classes. It does not claim a destructive restore rehearsal or measured recovery SLO.

## Validation evidence

Phase 4 evidence proves current snapshot status, an isolated off-cluster destination, positive size,
ready state, compression, schedule, retention, and protected credentials without recording raw
locations. Later recovery phases must add isolated restore, data checksum, endpoint validation,
measured RTO/RPO, and recovery-key protection before claiming end-to-end restore proof. Node
reconstruction and an etcd restore rehearsal provide deeper assurance.

## Production evolution

Use cross-account/region immutability, application-consistent database backups, scheduled DR rehearsals, key escrow, tested full-cluster rebuilds, and recovery SLOs.
