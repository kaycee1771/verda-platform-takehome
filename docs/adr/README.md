# Architecture Decision Records

ADRs record decisions whose consequences outlive a single implementation command.

## Status vocabulary

- **Proposed:** preferred direction, but a named Phase 0 gate must close first.
- **Accepted:** approved for the take-home implementation.
- **Superseded:** replaced by a later ADR; retained for history.
- **Rejected:** evaluated but not selected.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0000](0000-use-architecture-decision-records.md) | Use ADRs for material decisions | Accepted |
| [0001](0001-use-rke2-for-the-takehome-cluster.md) | Use RKE2 for the cluster | Accepted |
| [0002](0002-model-environments-as-isolated-namespaces.md) | Model environments as isolated namespaces | Accepted |
| [0003](0003-co-locate-rancher-for-the-takehome.md) | Co-locate Rancher for the take-home | Accepted |
| [0004](0004-use-longhorn-for-replicated-storage.md) | Use Longhorn for replicated storage | Proposed |
| [0005](0005-use-sealed-secrets-for-gitops-secrets.md) | Use Sealed Secrets for GitOps secrets | Accepted |
| [0006](0006-bootstrap-argo-cd-then-manage-declaratively.md) | Bootstrap Argo CD, then manage declaratively | Accepted |
| [0007](0007-treat-public-endpoint-ha-as-an-explicit-gap.md) | Treat public endpoint HA as an explicit gap | Proposed |
| [0008](0008-use-verda-object-storage-as-the-backup-target.md) | Use Verda object storage as backup target | Proposed |
