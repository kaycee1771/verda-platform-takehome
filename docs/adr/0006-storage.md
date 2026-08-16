# ADR 0006: Use Longhorn with Verda Object Storage as a Separate Recovery Domain

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Storage architecture
- **Blocking gates:** GATE-002, GATE-003, GATE-004

## Context

Harbor and other platform services require persistent storage and node-loss recovery. Provider 1.1.2 supports NVMe volume and attachment resources, while official Verda docs describe S3-compatible object storage with separate credentials. Account sizes, prices, attachment behavior, and compatibility are not yet proven.

## Decision

Subject to discovery, attach one dedicated Verda NVMe volume per node for Longhorn data and use node-spanning Longhorn replicas. Store recovery data and Loki object data in Verda object storage with separate buckets/prefixes and credentials where the account supports least privilege.

## Alternatives considered

- **OS-disk/local-path only:** lower complexity but weak node-loss recovery.
- **Rook/Ceph:** capable but too heavy for three general-purpose nodes.
- **In-cluster MinIO as only backup:** rejected because it shares the cluster failure domain.
- **External third-party S3:** valid fallback if Verda object storage is unavailable/incompatible.

## Consequences

- Replication consumes capacity by replica factor and depends on network/disk behavior.
- Longhorn requires narrow privileged/system exceptions.
- Replication and snapshots are not application-consistent off-cluster backups.

## Validation evidence

Account inventory, attachment lifecycle tests, Longhorn prerequisite checks, one-node failure/rebuild, capacity measurement, S3 compatibility, and checksum restore are required before acceptance.

## Production evolution

Choose a supported CSI/storage platform based on failure domains, IOPS, application consistency, encryption, and recovery objectives; isolate backup administration and retention.
