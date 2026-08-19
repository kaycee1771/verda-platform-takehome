# Verda Platform Engineer Take-Home

This repository is being built phase by phase as a reproducible, secure-by-design, observable, GitOps-driven Kubernetes platform on Verda Cloud. Every claimed capability must have code, automated verification where practical, rationale, and sanitized live evidence.

## Current status

**Phases 0–4 — PASS; Phase 5 is the active authorized boundary.** Verda currently runs exactly three
on-demand management instances with three instance-owned 80 GiB OS volumes and three protected
100 GiB data volumes. The Phase 2 closeout proved unique public endpoints, hostname-bound SSH,
encrypted external Terraform state and backup, guarded lifecycle behavior, reconciled cost, and
zero drift. Phase 3 added named key-only administration, fail-safe SSH/firewall transitions, a
three-node WireGuard mesh, guarded UUID-mounted data filesystems, two-pass idempotency, public-port
denial tests, and three serial reboot proofs. Phase 4 now has three Ready schedulable RKE2
server/etcd nodes, healthy Cilium/Hubble and service networking, internal Traefik, local plus
off-cluster snapshots, focused CIS checks on every server, a controlled one-node and primary-endpoint
failure drill, approved-source firewall verification, a sanitized support bundle, a zero-change
three-host replay, and a 270-second post-recovery stability window. Independent current-tree
verification, final local quality, PR validation, and protected-main hosted CI all passed.
Rancher, Argo CD, and Phase 5 platform components remain unimplemented until Phase 5 convergence;
Stage B and later components remain behind their owning gates.

The selected Stage A baseline is three on-demand `CPU.4V.16G` nodes in `FIN-03`, each with an 80 GiB
root volume and a 100 GiB Longhorn data volume, using Ubuntu 24.04 Minimal. The seven-day envelope
is $50.51, including a capped $5 unquoted-services allowance and 15% contingency against a verified
$115.67 starting balance. Kubernetes, endpoint, and object-storage gates are tracked in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Delivery architecture

- **Stage A — guaranteed pass path:** one three-node RKE2 management cluster temporarily hosts the platform and `demo-dev`, `demo-staging`, and `demo-prod`.
- **Stage B — staff-level target:** after Stage A is fully green and credits permit it, a second three-node RKE2 workload cluster receives the three application environments. Rancher, Argo CD, Harbor, and central troubleshooting services remain on the management cluster.
- Each cluster uses three schedulable RKE2 server nodes with embedded etcd. This controls take-home cost while retaining quorum; production evolution would normally separate control-plane and worker capacity.
- Cilium/Hubble, Longhorn plus off-cluster Verda object storage, immutable digest promotion, Argo CD, Harbor, Sealed Secrets, Kyverno, Prometheus/Grafana, Loki/Alloy, and layered recovery follow the accepted ADRs.

See [architecture.md](docs/architecture.md), [operations-model.md](docs/operations-model.md), and the [ADR index](docs/adr/README.md).

## Reproducible developer workflow

Prerequisites are Git, GNU Make, PowerShell 7, and a running Docker Linux daemon. Bootstrap is the
only networked quality step; all validation commands run in the same pinned non-root image with the
container network disabled and no cloud credential mounts.

```powershell
make help
make bootstrap-tools
make install-hooks
make validate
make validate-negative
make pre-commit
make secret-scan
make ci
```

`make ci` is the local equivalent of the validation job in `.github/workflows/validate.yml`.
The canonical 18-phase target map is `config/phase-map.json`. Phase 4 exposes only the explicit
completed-phase preflight/convergence targets plus `make cluster-bootstrap CLUSTER=management` and
`make verify-cluster CLUSTER=management`. Phase 2 cloud mutation, GitOps, platform services, Stage A
verification, Stage B, and teardown remain fail closed with their owning phase.

## Safe Phase 0 discovery

The account command is an allowlisted, read-only probe and requires explicit acknowledgement.

```powershell
make phase0-tools
make phase0-provider-schema
make phase0-discover-account
make phase0-validate
```

Cloud API credentials are time-bound and process-only. Never place their values in this repository,
command arguments, logs, Terraform plans, inventory, or evidence. A future live account probe must
use a separately authorized credential through the documented environment-variable boundary:

```powershell
verda auth login
```

Raw schema and account responses are written only to ignored `*.local.json` files. Committed evidence is sanitized and contains no project ID, credential, token, or secret value.

## Sources of truth

- [Implementation status](IMPLEMENTATION_STATUS.md)
- [Acceptance matrix](docs/acceptance-matrix.md)
- [Verda discovery report](docs/reports/verda-discovery.md)
- [Cost and capacity snapshot](docs/cost.md)
- [Known limitations](docs/known-limitations.md)
- [Risk register](docs/risk-register.md)
- [Version lock](versions.lock.yaml)
- [AI-use record](docs/ai-usage.md)
- [Security contract](SECURITY.md)
