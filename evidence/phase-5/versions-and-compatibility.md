# Phase 5 Versions and Compatibility

Status: PASS for source selection; live compatibility remains a separate gate.

The Phase 5 candidates were rechecked on 2026-08-19 against version-specific
official sources and exact downloaded chart archives:

| Component | Chart | Application | Kubernetes contract | Archive SHA-256 |
|---|---:|---:|---|---|
| Argo CD | 10.3.3 | v3.5.1 | chart `>=1.25`; current Argo line tests Kubernetes 1.35 | `ce254920357b323aad981e79ab8b1879c33835ef8efd4a1c91743f75e61d8007` |
| cert-manager | v1.21.1 | v1.21.1 | chart `>=1.22`; release 1.21 tests Kubernetes 1.33–1.36 | `c27101f3f3e2349fb4a9e704316105bf7b52ad73b8c8257d3498ef7f2f6a4adc` |
| Longhorn | 1.12.1 | v1.12.1 | chart `>=1.25`; 1.12 guidance includes Kubernetes 1.35 | `d70764e2d6cce673482da4d91da5b44a9791cda842c1914f77e7806ad1cd94bb` |

Sources:

- <https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/>
- <https://argoproj.github.io/argo-helm/index.yaml>
- <https://cert-manager.io/docs/releases/>
- <https://charts.jetstack.io/index.yaml>
- <https://longhorn.io/docs/1.12.0/best-practices/>
- <https://charts.longhorn.io/index.yaml>

The archives were acquired from the locked chart repositories and hashed before
use. CRD schemas for `Application`, `AppProject`, `Certificate`, `ClusterIssuer`,
Longhorn `Volume`, `Node`, and `Setting` are pinned to exact upstream release
sources and materialized into the offline schema cache. The current RKE2/Kubernetes
version remains v1.35.7+rke2r1 / v1.35.7.

This evidence does not claim that the charts are installed or healthy. Exact
render, admission, webhook readiness, API behavior, and rollback remain Phase 5
live gates.
