# ADR 0004: Use Longhorn for Replicated Storage

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Storage architecture
- **Blocking gates:** GATE-002, GATE-003, GATE-004

## Context

Harbor, Prometheus, and other components require persistence. Node-local volumes survive a pod restart but do not transparently recover workloads from a failed node. Verda exposes persistent volumes, but a Kubernetes CSI integration and multi-attach semantics have not yet been verified.

## Decision

Subject to discovery, attach one dedicated persistent NVMe volume to each node and use Longhorn to replicate Kubernetes volumes across nodes. Keep backups off-cluster in object storage; Longhorn replication is not a backup.

## Alternatives

- **Node-local provisioner:** simple and cheap, but creates node-affinity and recovery gaps.
- **Shared filesystem volume:** potentially simpler if supported, but semantics, performance, and Kubernetes integration are not yet verified.
- **Ceph/Rook:** capable but materially heavier for three general-purpose nodes and a short assessment.

## Consequences

- Stateful pods can be rescheduled after a node failure when replicas are healthy.
- Capacity overhead increases by the replica factor.
- Privileged components and host prerequisites require narrow Pod Security exceptions.
- Network latency and disk behavior become critical dependencies.

## Validation

- Dedicated disks are discovered and used only by Longhorn.
- Replica anti-affinity spans nodes.
- Volume remains usable after one-node loss.
- Snapshot, off-cluster backup, and restore pass with a checksum.
- Rebuild time and capacity headroom are measured.

## Reversal triggers

- No suitable per-node volume is available.
- Network or disk performance makes replication unstable.
- Resource overhead jeopardizes core components.
