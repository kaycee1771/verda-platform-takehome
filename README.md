# Verda Platform Engineering Take-Home

This repository will contain a reproducible, production-informed Kubernetes platform on Verda Cloud. The implementation is optimized for assessor clarity: every assignment requirement has an acceptance test, every material tradeoff has an ADR, and every production claim must have evidence.

## Current status

**Phase 0 - conditional go.** The architecture, requirement contract, risk model, provider schema, and read-only discovery workflow are implemented. No Verda resource has been created. Terraform 1.15.8, Verda CLI 1.8.1, and Verda provider 1.1.2 are verified; authenticated account discovery is waiting for local credentials.

Cloud provisioning is prohibited until the blocking Phase 0 gates are closed:

- Verda credentials are configured locally, never committed.
- Available CPU SKUs, images, locations, volumes, and prices are captured.
- Peer networking and ingress/load-balancing capabilities are verified.
- The selected topology fits the assignment credit budget.

See [the Phase 0 exit review](docs/phase-0-exit-review.md) for the authoritative gate state.

## Intended take-home topology

- Three CPU VMs running RKE2 server, embedded etcd, and worker roles.
- Rancher, Argo CD, Harbor with Trivy, kube-prometheus-stack, Loki, and platform controllers.
- Dev, staging, and production namespaces with RBAC, quotas, Pod Security Admission, and default-deny network policies.
- Persistent per-node storage with Longhorn replication, subject to Phase 0 capacity validation.
- Verda S3-compatible object storage for backups and log object storage, subject to account validation.

The repository separately documents the production target architecture, where Rancher and workloads run on separate clusters.

## Phase 0 commands

PowerShell 7 is required for the local scripts.

```powershell
pwsh -NoProfile -File scripts/phase0/validate.ps1
pwsh -NoProfile -File scripts/phase0/discover-tools.ps1
pwsh -NoProfile -File scripts/phase0/discover-verda.ps1
```

After the Verda CLI and local credentials are configured, explicitly opt into the read-only account query:

```powershell
pwsh -NoProfile -File scripts/phase0/discover-verda.ps1 `
  -QueryAccount `
  -ConfirmReadOnly `
  -OutputPath docs/evidence/phase-0/verda-discovery.local.json
```

After Terraform or OpenTofu is installed, download the provider and export its exact schema:

```powershell
pwsh -NoProfile -File scripts/phase0/export-provider-schema.ps1 `
  -AllowProviderDownload `
  -OutputPath docs/evidence/phase-0/provider-schema.local.json
```

Generated account discovery and provider schema files are intentionally ignored. Only a manually redacted evidence summary should be committed.

## Repository governance

- [Requirements and proof matrix](docs/requirements-matrix.md)
- [Architecture](docs/architecture.md)
- [Assumptions](docs/assumptions.md)
- [Risk register](docs/risk-register.md)
- [Cost model](docs/cost-model.md)
- [ADRs](docs/adr/README.md)
- [AI usage log](docs/ai-usage.md)
- [Security rules](SECURITY.md)
