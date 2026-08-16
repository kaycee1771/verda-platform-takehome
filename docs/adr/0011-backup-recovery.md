# ADR 0011: Use Layered Recovery and Require Restore Proof

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Recovery architecture
- **Blocking gates:** GATE-008 and live restore evidence

## Context

Git, Terraform state, etcd, Kubernetes objects, persistent volumes, component databases, and sealing keys have different recovery semantics. A successful backup job does not prove recoverability.

## Decision

Use Git for declarative state, protected Terraform state/backup for infrastructure lifecycle, RKE2 etcd snapshots for cluster state, Velero for Kubernetes resources/filesystem backups, Longhorn snapshot/backup for volume recovery, component-specific exports where consistency requires them, and an encrypted off-repository Sealed Secrets key backup. Use separate credentials/buckets/prefixes in a genuinely off-cluster S3-compatible target. Prefer Verda object storage only if the current project entitlement appears and compatibility passes; otherwise use ADR-0006's external S3 fallback.

## Alternatives considered

- **Only etcd snapshots:** insufficient for infrastructure lifecycle and independent volume/application recovery.
- **Only Velero:** insufficient for Terraform, sealing keys, and some component consistency requirements.
- **Only Longhorn replicas/snapshots:** shares failure domains and is not cluster/application recovery.

## Consequences

- Recovery has multiple runbooks and retention/credential dependencies.
- Recovery objectives must be stated per data class, not as one vague platform number.
- The current project does not expose Verda Object Storage Access Keys, so recovery cannot assume that target.
- This ADR remains Proposed until an off-cluster backup and checksum-verified restore pass.

## Validation evidence

At minimum: current snapshot/backup status, isolated destination, namespace/PVC deletion and restore, data checksum, endpoint test, measured RTO/RPO, and recovery-key protection. Node reconstruction and optional etcd restore add deeper proof.

## Production evolution

Use cross-account/region immutability, application-consistent database backups, scheduled DR rehearsals, key escrow, tested full-cluster rebuilds, and recovery SLOs.
