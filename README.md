# Verda Platform Engineer Take-Home

This repository is being built phase by phase as a reproducible, secure-by-design, observable, GitOps-driven Kubernetes platform on Verda Cloud. Every claimed capability must have code, automated verification where practical, rationale, and sanitized live evidence.

## Current status

**Phase 0 — BLOCKED.** Repository-side discovery and governance are implemented, but the Phase 0 exit gate is not satisfied. No Verda resource has been created or changed.

The blocking condition is concrete: this shell has neither `VERDA_CLIENT_ID` nor `VERDA_CLIENT_SECRET`, so current account locations, CPU shapes, OS image IDs, capacity, prices, credit balance, and account-specific networking cannot be inspected. Phase 1 must not begin until the failed conditions in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) are green.

## Delivery architecture

- **Stage A — guaranteed pass path:** one three-node RKE2 management cluster temporarily hosts the platform and `demo-dev`, `demo-staging`, and `demo-prod`.
- **Stage B — staff-level target:** after Stage A is fully green and credits permit it, a second three-node RKE2 workload cluster receives the three application environments. Rancher, Argo CD, Harbor, and central troubleshooting services remain on the management cluster.
- Each cluster uses three schedulable RKE2 server nodes with embedded etcd. This controls take-home cost while retaining quorum; production evolution would normally separate control-plane and worker capacity.
- Cilium/Hubble, Longhorn plus off-cluster Verda object storage, immutable digest promotion, Argo CD, Harbor, Sealed Secrets, Kyverno, Prometheus/Grafana, Loki/Alloy, and layered recovery follow the accepted ADRs.

See [architecture.md](docs/architecture.md), [operations-model.md](docs/operations-model.md), and the [ADR index](docs/adr/README.md).

## Safe Phase 0 commands

PowerShell 7 is required. The account command is an allowlisted, read-only probe and requires explicit acknowledgement.

```powershell
make phase0-tools
make phase0-provider-schema
make phase0-discover-account
make phase0-validate
```

Before the account probe, configure credentials locally without placing them in this repository. The interactive CLI keeps the value out of command history and repository files:

```powershell
verda auth login
```

Raw schema and account responses are written only to ignored `*.local.json` files. Committed evidence is sanitized and contains no project ID, credential, token, or secret value.

## Phase 0 source of truth

- [Implementation status](IMPLEMENTATION_STATUS.md)
- [Acceptance matrix](docs/acceptance-matrix.md)
- [Verda discovery report](docs/reports/verda-discovery.md)
- [Cost and capacity snapshot](docs/cost.md)
- [Known limitations](docs/known-limitations.md)
- [Risk register](docs/risk-register.md)
- [Version lock](versions.lock.yaml)
- [AI-use record](docs/ai-usage.md)
- [Security contract](SECURITY.md)
