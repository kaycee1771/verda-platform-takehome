# Assignment Requirements and Proof Contract

This is the authoritative traceability matrix. A component being installed is not sufficient; each requirement must have observable proof and a repeatable verification path.

## Deliverables

| ID | Requirement | Implementation contract | Required proof | State |
|---|---|---|---|---|
| DEL-001 | Git repository with manifests, scripts, and docs | All infrastructure, bootstrap, platform, app, policy, and runbook assets are versioned | Clean clone plus successful `make validate` and repository map | Contracted |
| DEL-002 | Access instructions | Publish sanitized URLs, IPs, ports, user roles, tunnel steps, credential delivery, expiry, and revocation | Independent assessor follows `docs/access.md` without author assistance | Contracted |
| DEL-003 | One-page summary | Exactly one page covering build, results, failures, tradeoffs, gaps, and cost | Rendered one-page PDF or print preview with no overflow | Contracted |

## Core requirements

| ID | Requirement | Implementation contract | Acceptance test and evidence | State |
|---|---|---|---|---|
| CORE-001 | Kubernetes cluster | Three-node RKE2 cluster with embedded-etcd quorum and pinned version | Nodes Ready; etcd healthy; cluster remains functional during one-node loss | Contracted |
| CORE-002 | Rancher cluster management | Three-replica Rancher deployment on the take-home cluster | Rancher reports the local cluster Active and exposes nodes/workloads to an assessor role | Contracted |
| CORE-003 | Argo CD GitOps | Pinned Argo CD bootstrap, root application, AppProjects, and ApplicationSets | All applications Healthy/Synced; manual drift is detected and reconciled | Contracted |
| CORE-004 | Image registry and scanning | Harbor with Trivy, TLS, robot account, immutable releases, scan-on-push, and retention | CI pushes an immutable artifact; Harbor shows scan results; threshold failure is demonstrated | Contracted |
| CORE-005 | Metrics, dashboards, and alerts | kube-prometheus-stack plus application ServiceMonitor, SLO dashboard, and actionable PrometheusRules | Saved PromQL queries; dashboard evidence; at least one alert deliberately fires and resolves | Contracted |
| CORE-006 | Searchable centralized logs | Grafana Alloy collects structured logs into Loki backed by object storage where validated | Saved LogQL query locates a known request/error by environment, workload, and correlation ID | Contracted |
| CORE-007 | Dev, staging, prod and promotion | Isolated namespaces generated from Kustomize overlays and Argo CD ApplicationSets | One immutable image digest moves through reviewed Git commits; revert performs rollback | Contracted |

## Bonus requirements

| ID | Requirement | Implementation contract | Acceptance test and evidence | State |
|---|---|---|---|---|
| BONUS-001 | RBAC and network policies | Environment roles, Argo projects, default-deny ingress/egress, and explicit allows | Expected allowed and denied operations and connections are tested | Contracted |
| BONUS-002 | Backup and restore | RKE2 snapshots, Velero, Longhorn data backup, and component-specific recovery runbooks | Delete and restore the dev workload; verify state and checksum; record RTO | Contracted |
| BONUS-003 | Pod security policies | Implement the current intent with restricted Pod Security Admission and Kyverno because PSP was removed in Kubernetes 1.25 | A non-compliant pod is rejected; exceptions are narrow and documented | Contracted |
| BONUS-004 | Cost analysis | Actual Verda compute, volume, object-storage, and retention costs with lean/recommended scenarios | Prices are sourced from read-only discovery and reconciled to the running inventory | Contracted |
| BONUS-005 | GPU nodes | Optional tainted GPU worker only if available credits and capacity preserve the core platform | Schedulable GPU resource and metrics are demonstrated | Capacity-gated |
| BONUS-006 | Kueue | CPU queue baseline; optional GPU ResourceFlavor | Jobs visibly queue, admit, run, and respect quota | Core-first |

## Evaluation criteria

| ID | Evaluation signal | Repository response | Evidence |
|---|---|---|---|
| EVAL-001 | Systematic provisioning and debugging | Terraform, Ansible, idempotent commands, layered diagnostics, and failure runbooks | Clean-run transcript and `make doctor` output |
| EVAL-002 | Architectural understanding | Implemented and production-target views, ADRs, failure domains, and ownership boundaries | Architecture review and ADR index |
| EVAL-003 | Tradeoff reasoning | Each material decision records options, consequences, and reversal trigger | Accepted/proposed ADRs and risk register |
| EVAL-004 | Honest reporting | HA and security claims are evidence-bound; unresolved gaps remain visible | One-page summary and exit reviews |
| EVAL-005 | Effective AI usage | AI contributions, validation, rejections, and human decisions are recorded | `docs/ai-usage.md` |

## Definition of proof

Evidence must be reproducible, sanitized, dated, and tied to a commit. Screenshots may support evidence but never replace machine-readable command output or an automated acceptance test.
