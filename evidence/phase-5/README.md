# Phase 5 Evidence Index

Status: PARTIAL — every Phase 5 live exit gate and final current-tree local CI
passed; hosted closeout CI remains pending.

| Evidence | State |
|---|---|
| [versions-and-compatibility.md](versions-and-compatibility.md) | PASS — official source review, archive integrity, and live compatibility |
| [preflight-cluster-health.md](preflight-cluster-health.md) | PASS — protected preflight and independent direct access |
| [gitops-bootstrap.md](gitops-bootstrap.md) | PASS — idempotent bounded bootstrap and exact GitOps ownership |
| [longhorn-reschedule.md](longhorn-reschedule.md) | PASS — dedicated disks, critical checksum reschedule, and cleanup |
| [tls-access-and-boundary.md](tls-access-and-boundary.md) | PASS — certificates, TLS, authentication, RBAC, and external boundary |
| [capacity-before-after.md](capacity-before-after.md) | PASS — positive post-install one-node-loss headroom |
| [repository-validation.md](repository-validation.md) | PASS — final current-tree local CI |
| [hosted-ci.md](hosted-ci.md) | PENDING — protected closeout workflow |
| [exit-gates.md](exit-gates.md) | PARTIAL — live and local gates PASS; hosted closeout PENDING |
| [completion-report.md](completion-report.md) | PARTIAL — Section 35.20 candidate awaiting hosted closeout |

Only sanitized aggregate scalars are curated. Raw Kubernetes payloads, application
or storage identities, addresses, certificate bodies, kubeconfigs, session values,
credentials, Terraform state, and live command logs remain outside Git.
