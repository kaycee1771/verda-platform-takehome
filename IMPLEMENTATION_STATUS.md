# Implementation Status

## Current state

- Active phase: Phase 5 — LIVE GATES PASS / CLOSEOUT PARTIAL
- Phase status: PARTIAL — bootstrap, GitOps ownership, storage resilience, TLS, authentication, endpoint-boundary, and final local CI gates pass; hosted closeout CI is pending
- Stage A status: PHASE 5 PLATFORM BOUNDARY READY — three-node RKE2, Argo CD, cert-manager, authenticated TLS ingress, and three-node Longhorn are live; Phase 6 remains fail closed until Phase 5 closeout is merged
- Stage B status: NOT STARTED — prohibited until Stage A is green and the Stage B decision gate passes
- Last protected-main hosted baseline: commit `adc0a071d69852e30659f07999aa95f50401027b`, run `32299258822`, job `96217807991`; validation passed before final evidence curation
- Definitive Phase 5 live-verification source: protected `main` commit `adc0a071d69852e30659f07999aa95f50401027b`; the final evidence-curated hosted closeout identity is pending
- Current blocker: the hosted closeout workflow is not yet recorded and merged
- Cloud mutation performed: the original seven-resource plan plus one explicitly authorized, assertion-bounded replacement of server-02 compute/OS only; `verda-mgmt-data-02` was preserved
- Next permitted action: publish through the protected review path and record hosted closeout CI; do not begin Phase 6 before merge

## Phase ledger

| Phase | Status | Started | Completed | Evidence | Notes |
|---|---|---|---|---|---|
| 0 — Engineering contract and discovery | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-0/` | Provider, account catalog, network boundary, and seven-day cost envelope verified |
| 1 — Repository and quality system | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-1/` | Local and hosted gates pass; protected public repository is operational |
| 2 — Verda infrastructure provisioning | PASS | 2026-08-17 | 2026-08-17 | `evidence/phase-2/` | Exact resources, unique endpoints, three-host SSH, lifecycle safety, cost, encrypted state, and zero drift verified |
| 3 — Host hardening and secure node networking | PASS | 2026-08-17 | 2026-08-17 | `evidence/phase-3/` | Hardened access, UUID mounts, peer-only WireGuard, firewall, two-pass idempotency, and three serial reboots verified |
| 4 — Management RKE2 cluster | PASS | 2026-08-18 | 2026-08-19 | `evidence/phase-4/` | Live, local, PR, and protected-main hosted gates pass |
| 5 — Storage, ingress, certificates, and bootstrap boundary | PARTIAL | 2026-08-19 | — | `evidence/phase-5/` | All live and final local gates pass; hosted closeout quality pending |

## Environment inventory

| Resource | ID | Address | Role | Created | Expiry |
|---|---|---|---|---|---|
| `verda-mgmt-server-01` | redacted | unique/redacted | Ready schedulable RKE2 server/etcd node | 2026-08-17 | 2026-08-24 |
| `verda-mgmt-server-02` | redacted | unique/redacted | Ready schedulable replacement RKE2 server/etcd node | 2026-08-17 | 2026-08-24 |
| `verda-mgmt-server-03` | redacted | unique/redacted | Ready schedulable RKE2 server/etcd node | 2026-08-17 | 2026-08-24 |
| `verda-mgmt-data-01..03` | redacted | attached | ext4, UUID-mounted at `/var/lib/longhorn`, 100 GiB each, reboot PASS | 2026-08-17 | preserve through compute rollback |

## Phase 2 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| Exact provider schema/catalog/cost revalidated | PASS | `evidence/phase-2/provider-runtime-findings.md` | Retain live fail-closed preflight |
| Exact three instances and three persistent data volumes | PASS | `evidence/phase-2/live-resource-verification.md` | No additional resources permitted |
| Every management host has a unique public IP and intended-key SSH | PASS | `evidence/phase-2/live-resource-verification.md` | Recheck before Phase 3 host mutation |
| Repeat plan has no unexpected drift | PASS | `evidence/phase-2/recovery-and-exit-gates.md` | Preserve the plan assertion on every future change |
| Encrypted external state and independent backup | PASS | `evidence/phase-2/state-boundary.md` | Keep DPAPI wrapper canonical; remote S3 remains deferred |
| Teardown/rollback behavior proven safe | PASS | full destroy rejected; exact three-instance compute rollback plan asserted; data volumes use `prevent_destroy` | Keep the two-part destructive guard |
| Final hosted credential-free CI on merged Phase 2 | PASS | `evidence/phase-2/hosted-ci.md`; commit `4d05890fa22edd126ff25df195bf93e2e3cf33eb`; run `32012648406` | Refresh again when Phase 3 is published |

## Phase 3 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| All three hosts pass the baseline | PASS | `evidence/phase-3/host-hardening-report.md` | Repeat diagnostics before Phase 4 |
| Internal node addressing is stable | PASS | `evidence/phase-3/wireguard-reachability.md` | Keep mapping explicit; reconcile any provider endpoint change |
| Firewall rules are validated | PASS | `evidence/phase-3/external-port-scan.md` | Extend matrix explicitly before RKE2 starts |
| Reboot preserves configuration | PASS | `evidence/phase-3/reboot-and-exit-gates.md` | Retain serial, boot-identity-verified maintenance |
| Candidate retains safe administrative access | PASS | `evidence/phase-3/host-hardening-report.md` | Current source `/32` remains an external runtime input |
| Complete playbook is idempotent | PASS | `evidence/phase-3/ansible-idempotency.md` | First, second, final, and post-reboot recaps are clean |
| RKE2 remained absent at Phase 3 closure | PASS | `evidence/phase-3/reboot-and-exit-gates.md` | Historical isolation gate; later satisfied by the authorized Phase 4 bootstrap |

## Phase 4 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| Exact compatible version and immutable artifacts | PASS | `evidence/phase-4/version-selection.md` | Retain exact locks |
| Live resource, drift, host, access, route, and cost boundary | PASS | `evidence/phase-4/live-preflight.md`; `cidr-design.md` | Repeat before later host mutation |
| Serial three-server installation and common-config parity | PASS | `management-installation.md`; `common-config-parity.md` | Treat critical values as rebuild-only |
| Nodes, API, system pods, etcd, Cilium, Hubble, DNS/service, policy, Traefik, and MTU | PASS | Curated management evidence under `evidence/phase-4/` | Retain source-controlled verification |
| Scheduled local and off-cluster snapshots | PASS | `management-snapshots.md`; `manual-object-storage-exception.md` | Keep manual lifecycle explicit |
| Focused CIS, audit, and secrets-encryption checks on all servers | PASS | `management-cis-assessment.md` | Retain manual identity exception |
| Final external firewall scan | PASS | `management-firewall-scan.md` | Approved-source scan; second vantage remains a documented limitation |
| Non-primary and primary-endpoint fault drills | PASS | `management-node-failure.md`; `management-endpoint-failure.md` | One-node boundary only; two-node loss deliberately excluded |
| Stability and active-cluster idempotency | PASS | `stability-and-idempotency.md` | Current tree preserves recovered restart history before the stability baseline |
| Sanitized support bundle | PASS | `management-support-bundle.md` | Raw archive remains ignored and outside curation |
| Independent current-tree verification | PASS | `independent-verification.md` | Retain the final recovery and Cilium acceptance corrections |
| Final local quality | PASS | `repository-validation.md` | Retain exact current-tree CI parity |
| Final hosted quality | PASS | `hosted-ci.md` | Retain PR and protected-main runs |

## Phase 5 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| Pinned bootstrap is idempotent and bounded to Argo CD plus one root Application | PASS | `evidence/phase-5/gitops-bootstrap.md` | Preserve the day-zero/day-one ownership boundary |
| Argo CD owns the exact root/child desired-state set | PASS | `evidence/phase-5/gitops-bootstrap.md` | Retain exact-set and Healthy/Synced verification |
| cert-manager staging-first promotion and production TLS | PASS | `evidence/phase-5/tls-access-and-boundary.md` | Keep issuer references and certificate expiry checks exact |
| Longhorn uses three dedicated disks and survives critical-volume rescheduling | PASS | `evidence/phase-5/longhorn-reschedule.md` | Preserve three replicas for critical data and root-disk exclusion |
| Management ingress requires authentication and reviewer privileges are read-only | PASS | `evidence/phase-5/tls-access-and-boundary.md` | Rotate protected external sessions without widening RBAC |
| Direct break-glass Kubernetes access remains independent of Rancher | PASS | `evidence/phase-5/preflight-cluster-health.md` | Keep kubeconfig outside Git with mode `0600` |
| External endpoint boundary is exact on all three nodes | PASS | `evidence/phase-5/tls-access-and-boundary.md` | Retain the four allowed and 28 denied port classes |
| Post-install capacity retains one-node-loss headroom | PASS | `evidence/phase-5/capacity-before-after.md` | Re-evaluate exact Phase 6 requests and PVCs before admission |
| Final current-tree local CI | PASS | `evidence/phase-5/repository-validation.md` | Retain exact offline/credential-free parity |
| Final hosted closeout CI | PENDING | `evidence/phase-5/hosted-ci.md` | Publish only after local CI, then record protected result |

## Phase 0 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| Exact provider schema inspected | PASS | `evidence/phase-0/provider-schema-summary.md` | Re-check immediately before Phase 2 provider code |
| OS image and CPU instance type choices known | PASS | `evidence/phase-0/verda-account-discovery.md` | Revalidate availability immediately before apply |
| Networking limitations documented from current account | PASS | `evidence/phase-0/network-capability-surface.md` and ADR-0005 | Run live WireGuard, MTU, port, and endpoint-failure tests before RKE2 |
| Acceptance matrix complete | PASS | `docs/acceptance-matrix.md` | Keep current through every phase |
| Stage A has a credible cost envelope within credits | PASS | `docs/cost.md` and `evidence/phase-0/stage-a-cost-envelope.md` | Reconcile balance/rates before apply and daily while resources run |

## Phase 1 exit-gate ledger

| Gate condition | Result | Evidence | Closure action |
|---|---|---|---|
| Malformed Terraform is rejected | PASS | `.local/reports/negative/malformed-terraform.log` and Phase 1 summary | Retain generated ignored fixture |
| Invalid Kubernetes object is rejected | PASS | `.local/reports/negative/invalid-kubernetes-object.log` and Phase 1 summary | Retain strict Kubernetes 1.35 schemas |
| Missing custom schema is fatal | PASS | `.local/reports/negative/missing-custom-schema.log` and Phase 1 summary | Never enable a global ignore-missing flag |
| Invalid alert rule is rejected | PASS | `.local/reports/negative/invalid-alert-rule.log` and Phase 1 summary | Keep executable Prometheus harness |
| Generated private key is detected | PASS | `.local/reports/negative/generated-private-key.log` and Phase 1 summary | Fixture stays ignored and is deleted after the test |
| No unexplained repository directory exists | PASS | `tests/static/repository-contract.yaml` | Update ownership contract with each structural change |
| Full local CI parity passes | PASS | `.local/logs/ci.log` and `evidence/phase-1/` | Retain networkless, credential-free execution |
| Clean clone bootstraps and validates | PASS | `evidence/phase-1/clean-clone.md` | Repeat after any material quality-system change |
| Hosted GitHub Actions validation passes | PASS | `evidence/phase-1/hosted-ci.md`; run `31961790627` | Retain the credential-free workflow and seven-day reports |
| Protected `main` and real ownership are enforced | PASS | `evidence/phase-1/repository-governance.md` | Keep the GitHub Actions app-bound check, PR boundary, and no-force-push policy |

## Deferred gates

- Phase 2: a time-bound, project-scoped Cloud API credential exists outside Git. Its values were process-only during commands and were removed when the authenticated shell terminated; they were never requested in chat, printed, persisted, or included in plans/evidence. Revoke the account credential during teardown or at expiry.
- Phase 3 closure: the public-IP plus WireGuard path, 1420 host-overlay MTU, 1370 Cilium MTU, peer routing, firewall, storage, and reboot behavior remain live-verified beneath the management cluster.
- Object storage: Verda enabled the project entitlement and the authorized manual provider-gap path now proves local and off-cluster RKE2 snapshots. Bucket and credential lifecycle remain manual teardown obligations.
- Phase 4 access recovery: the changed administrator source was reconciled through the explicitly authorized rollback-protected exact-source workflow; the dynamic `/32` model remains an accepted residual risk.
- Security posture: no credential, token, coupon, raw UUID, endpoint value, SSH private key, or WireGuard private key is committed; GitHub secret scanning and push protection remain enabled. The operator-provided credential image must be deleted and its credential rotated after the authenticated work window.
