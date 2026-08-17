# ADR 0006: Use Longhorn with a Separate S3-Compatible Recovery Domain

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Storage architecture
- **Blocking gates:** Phase 2 attachment lifecycle evidence and GATE-008 before Phase 5

## Context

Harbor and other platform services require persistent storage and node-loss recovery. Provider 1.1.2 supports NVMe volume and attachment resources. The current console confirms single-instance NVMe volumes in FIN-01/02/03 at $0.20/GiB-month. Stage A selects one 100 GiB data volume plus an 80 GiB root volume per node.

Current official docs describe S3-compatible object storage with separate credentials, default endpoint `https://objects.fin-03.verda.storage`, and region `us-east-1`. However, this project's Credentials page does not expose Object Storage Access Keys and local S3 status is unconfigured. Verda object-storage entitlement is therefore not assumed.

## Decision

Subject to Phase 2 lifecycle proof, attach one dedicated Verda NVMe volume per node for Longhorn data and use node-spanning replicas. Critical Stage A volumes normally use three replicas; lower-value data may use two only when capacity evidence justifies the reduced protection.

Use a genuinely off-cluster S3-compatible target for recovery data and Loki objects:

1. Prefer Verda object storage if entitlement appears and TLS, path style, least privilege, bucket lifecycle, price, and application compatibility pass.
2. Otherwise select the already approved external third-party S3 alternative through an explicit implementation note without presenting it as Verda-managed.
3. Never use in-cluster MinIO as the only backup target.

## Alternatives considered

- **OS-disk/local-path only:** lower complexity but weak node-loss recovery.
- **Rook/Ceph:** capable but too heavy for three general-purpose nodes.
- **In-cluster MinIO as only backup:** rejected because it shares the cluster failure domain.
- **External third-party S3:** accepted fallback if Verda object storage remains unavailable/incompatible.
- **Shared filesystem as Kubernetes storage:** current provider cannot model it and it does not replace application-consistent backup.

## Consequences

- Three-replica critical data consumes raw capacity by roughly 3× and depends on WireGuard/network/disk health.
- Longhorn requires narrow privileged/system exceptions.
- Replication and snapshots are not application-consistent off-cluster backups.
- The selected lean 300 GiB raw Stage A data tier provides roughly 100 GiB critical usable capacity before overhead; retention and the 60% cut line are operational requirements.
- Off-cluster storage configuration cannot begin until GATE-008 closes.

## Validation evidence

Before acceptance: verify volume create/attach/detach/preserve/delete behavior, stable device identity, idempotent format/mount, reboot persistence, Longhorn prerequisites, one-node failure/rebuild, capacity/latency, and protection against accidental deletion. Separately prove S3 TLS/path-style/credential scope, bucket lifecycle, backup status, checksum restore, and actual cost.

Phase 2 proved protected attachment lifecycle and compute replacement without data-volume loss.
Phase 3 then proved exact stable attachment identity, complete zero-media inspection before first
format, ext4 creation only when absent, UUID-based `/var/lib/longhorn` persistence, ownership/free
space, iSCSI/NFS/crypt prerequisites, idempotency, and survival across all three serial reboots.
ADR status remains Proposed because Longhorn, replica failure/rebuild, off-cluster S3, backup, and
restore are Phase 5/13 work and have not been implemented.

## Production evolution

Choose a supported CSI/storage platform based on failure domains, IOPS, application consistency, encryption, and recovery objectives; isolate backup administration and retention across accounts/regions with immutability where available.
