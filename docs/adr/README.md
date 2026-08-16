# Architecture Decision Records

ADRs preserve why a choice was made and what evidence may reverse it. The pre-blueprint baseline is retained in Git history at commit `7de5145`; ADR-0002 records the material correction from a one-cluster final target to Stage A plus conditional Stage B.

## Status vocabulary

- **Proposed:** preferred direction blocked by named discovery or evidence.
- **Accepted:** approved implementation contract; live implementation may still be pending.
- **Superseded:** replaced by a later ADR and retained for history.
- **Rejected:** evaluated but not selected.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0000](0000-use-architecture-decision-records.md) | Use ADRs for material decisions | Accepted |
| [0001](0001-rke2.md) | RKE2 distribution | Accepted |
| [0002](0002-two-stage-topology.md) | Stage A then separate Stage B workload cluster | Accepted |
| [0003](0003-cluster-role-layout.md) | Three schedulable server nodes per cluster | Accepted |
| [0004](0004-cilium.md) | RKE2-bundled Cilium and Hubble | Accepted |
| [0005](0005-network-endpoints.md) | WireGuard plus explicit public endpoint path | Accepted |
| [0006](0006-storage.md) | Longhorn plus separate S3-compatible recovery domain | Proposed |
| [0007](0007-gitops.md) | Minimal Argo bootstrap and Git-owned desired state | Accepted |
| [0008](0008-registry-supply-chain.md) | Harbor and build-once digest promotion | Accepted |
| [0009](0009-secret-management.md) | Sealed Secrets for take-home runtime secrets | Accepted |
| [0010](0010-observability.md) | Per-cluster Prometheus, central Grafana/Loki, Alloy | Accepted |
| [0011](0011-backup-recovery.md) | Layered backup and restore proof | Proposed |

Use [template.md](template.md) for later decisions.
