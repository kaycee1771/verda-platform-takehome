# Verda Platform Engineer Take-Home

This repository is being built phase by phase as a reproducible, secure-by-design, observable, GitOps-driven Kubernetes platform on Verda Cloud. Every claimed capability must have code, automated verification where practical, rationale, and sanitized live evidence.

## Current status

**Phase 0 — PASS.** Governance, provider-schema inspection, authenticated account discovery, endpoint-path selection, and the seven-day Stage A cost envelope are complete. No Verda resource has been created or changed.

The selected Stage A baseline is three on-demand `CPU.4V.16G` nodes in `FIN-03`, each with an 80 GiB root volume and a 100 GiB Longhorn data volume, using Ubuntu 24.04 Minimal. The seven-day envelope is $50.51 including a capped $5 unquoted-services allowance and 15% contingency against a verified $115.67 balance. Phase 1 remains deliberately not started; later credentials, live networking, and object-storage gates are tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

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

Before a future CLI account probe, configure credentials locally without placing them in this repository. Cloud API credentials do not currently exist and must be created before Phase 2. The interactive CLI keeps values out of command history and repository files:

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
