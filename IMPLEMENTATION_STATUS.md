# Implementation Status

## Current state

- Active phase: Phase 3 — PASS / COMPLETE; Phase 4 is not authorized
- Phase status: COMPLETE — all live host, access, storage, WireGuard, firewall, idempotency, reboot, evidence, and repository gates pass
- Stage A status: HOST FOUNDATION READY — three hardened, reboot-stable hosts and their protected data mounts are ready; Kubernetes has not started
- Stage B status: NOT STARTED — prohibited until Stage A is green and the Stage B decision gate passes
- Last successful repository verification: final complete local `make ci` after Phase 3 live acceptance on 2026-08-17; Phase 3 static/runtime unit tests, Terraform tests, warning-free TFLint/Ansible, zero-finding Trivy, schemas/policies, negative gates, pre-commit, and repeated history scanning passed
- Current blockers: no Phase 3 blocker; Phase 4 remains an authorization gate
- Cloud mutation performed: the original seven-resource plan plus one explicitly authorized, assertion-bounded replacement of server-02 compute/OS only; `verda-mgmt-data-02` was preserved
- Next permitted action: retain Phase 3 verification and request explicit authorization before any Phase 4 RKE2 work

## Phase ledger

| Phase | Status | Started | Completed | Evidence | Notes |
|---|---|---|---|---|---|
| 0 — Engineering contract and discovery | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-0/` | Provider, account catalog, network boundary, and seven-day cost envelope verified |
| 1 — Repository and quality system | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-1/` | Local and hosted gates pass; protected public repository is operational |
| 2 — Verda infrastructure provisioning | PASS | 2026-08-17 | 2026-08-17 | `evidence/phase-2/` | Exact resources, unique endpoints, three-host SSH, lifecycle safety, cost, encrypted state, and zero drift verified |
| 3 — Host hardening and secure node networking | PASS | 2026-08-17 | 2026-08-17 | `evidence/phase-3/` | Hardened access, UUID mounts, peer-only WireGuard, firewall, two-pass idempotency, and three serial reboots verified |

## Environment inventory

| Resource | ID | Address | Role | Created | Expiry |
|---|---|---|---|---|---|
| `verda-mgmt-server-01` | redacted | unique/redacted | Hardened management host; key-only named admin and WireGuard PASS | 2026-08-17 | 2026-08-24 |
| `verda-mgmt-server-02` | redacted | unique/redacted | Hardened replacement host; key-only named admin and WireGuard PASS | 2026-08-17 | 2026-08-24 |
| `verda-mgmt-server-03` | redacted | unique/redacted | Hardened management host; key-only named admin and WireGuard PASS | 2026-08-17 | 2026-08-24 |
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
| RKE2 remains absent | PASS | `evidence/phase-3/reboot-and-exit-gates.md` | Phase 4 hard gate remains in place |

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
- Phase 3 closure: the public-IP plus WireGuard path, 1420 host-overlay MTU, reserved 1370 Cilium MTU, peer routing, firewall, storage, and reboot behavior are live-verified. Kubernetes endpoint/failure behavior remains Phase 4+.
- Phase 5: the current project Credentials page does not expose Object Storage Access Keys even though current official documentation describes them. Confirm entitlement with Verda or activate the ADR-approved external S3 fallback before relying on off-cluster backup/Loki storage.
- Security posture: no credential, token, coupon, raw UUID, endpoint value, SSH private key, or WireGuard private key is committed; GitHub secret scanning and push protection remain enabled. The operator-provided credential image must be deleted and its credential rotated after the authenticated work window.
