# ADR 0008: Use Verda Object Storage as the Backup Target

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Recovery architecture
- **Blocking gates:** GATE-001, GATE-002, GATE-004

## Context

Backups stored only on cluster nodes share the cluster failure domain. Verda documents S3-compatible object storage with independent credentials. Compatibility with RKE2 snapshot upload, Velero, Longhorn, and Loki must still be tested against the assigned account endpoint.

## Decision

Use separate object-storage prefixes or buckets and least-privilege credentials for:

- RKE2 etcd snapshots.
- Velero Kubernetes object and volume backups.
- Longhorn backup data when supported.
- Loki chunks and indexes when the selected deployment mode requires them.
- Component-specific exports such as Harbor database backups.

Backup credentials remain outside Git and outside the workload namespaces.

## Alternatives

- **Node-local backups:** rejected as the only copy because they share host and cluster failure domains.
- **A second in-cluster MinIO deployment:** adds state but does not create an independent failure domain.
- **External third-party object storage:** valid fallback but less platform-native for this assignment.

## Consequences

- Recovery data survives cluster destruction.
- Object-store availability, retention, encryption, and credentials become recovery dependencies.
- Separate component paths simplify least privilege and lifecycle policies.
- Configuration is incomplete until an actual restore succeeds.

## Validation

- S3 API compatibility test succeeds without broad credentials.
- Backup objects appear under expected prefixes and retention rules.
- A deleted dev workload and persistent checksum are restored.
- Recovery succeeds using documented credentials from outside the cluster.

## Reversal triggers

- The assigned account lacks object storage or required S3 compatibility.
- Cost or policy requires an external backup provider.
