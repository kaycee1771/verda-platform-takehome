# Implementation Status

## Current state

- Active phase: Phase 1 — repository and quality system; external CI evidence pending
- Phase status: PARTIAL — all local gates pass; hosted GitHub Actions run is unavailable without a remote
- Stage A status: NOT STARTED — Phase 2 has not been authorized
- Stage B status: NOT STARTED — prohibited until Stage A is green and the Stage B decision gate passes
- Last successful end-to-end verification: Phase 1 clean-clone bootstrap, standalone gates, and full local CI-equivalent suite at `853beeb`
- Current blockers: Phase 1 hosted CI evidence and branch enforcement require a GitHub remote and real owner; Cloud API credentials block Phase 2, live peer-path tests block Phase 3, and object-storage entitlement blocks the Phase 5 off-cluster storage path
- Cloud mutation authorized: No
- Next permitted action: Complete Phase 1 clean-clone and hosted CI evidence only; Phase 2 remains prohibited

## Phase ledger

| Phase | Status | Started | Completed | Evidence | Notes |
|---|---|---|---|---|---|
| 0 — Engineering contract and discovery | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-0/` | Provider, account catalog, network boundary, and seven-day cost envelope verified |
| 1 — Repository and quality system | PARTIAL | 2026-08-16 | — | `evidence/phase-1/` | Local implementation and gates complete; hosted GitHub run pending |

## Environment inventory

| Resource | ID | Address | Role | Created | Expiry |
|---|---|---|---|---|---|
| None | — | — | Phase 0 creates no cloud resources | — | — |

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
| Hosted GitHub Actions validation passes | BLOCKED | No GitHub remote is configured | Publish after approval, set real CODEOWNERS, require the workflow, retain run URL |

## Deferred gates

- Phase 2: the current project has no Cloud API credentials. Create a least-privilege credential outside Git immediately before Terraform work; never place the value in a command, file, evidence, or commit.
- Phase 3: console/schema/CLI inspection selects the public-IP plus WireGuard path, but MTU, peer routing, firewall, and endpoint-failure behavior require live nodes.
- Phase 5: the current project Credentials page does not expose Object Storage Access Keys even though current official documentation describes them. Confirm entitlement with Verda or activate the ADR-approved external S3 fallback before relying on off-cluster backup/Loki storage.
- Security posture: no credential, token, coupon, private key, or cloud resource was created, captured, or committed in Phase 0.
