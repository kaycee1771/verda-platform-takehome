# Implementation Status

## Current state

- Active phase: Phase 0 — complete; awaiting explicit authorization to begin Phase 1
- Phase status: PASS
- Stage A status: NOT STARTED — Phase 1 repository quality system is next
- Stage B status: NOT STARTED — prohibited until Stage A is green and the Stage B decision gate passes
- Last successful end-to-end verification: None; no cloud resources exist
- Current blockers: none for Phase 0; Cloud API credentials block Phase 2, live peer-path tests block Phase 3, and object-storage entitlement blocks the Phase 5 off-cluster storage path
- Cloud mutation authorized: No
- Next permitted action: Phase 1 repository and quality system only, after explicit user instruction

## Phase ledger

| Phase | Status | Started | Completed | Evidence | Notes |
|---|---|---|---|---|---|
| 0 — Engineering contract and discovery | PASS | 2026-08-16 | 2026-08-16 | `evidence/phase-0/` | Provider, account catalog, network boundary, and seven-day cost envelope verified |
| 1 — Repository and quality system | NOT STARTED | — | — | — | Next approved phase; no Phase 1 work was performed in Phase 0 |

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

## Deferred gates

- Phase 2: the current project has no Cloud API credentials. Create a least-privilege credential outside Git immediately before Terraform work; never place the value in a command, file, evidence, or commit.
- Phase 3: console/schema/CLI inspection selects the public-IP plus WireGuard path, but MTU, peer routing, firewall, and endpoint-failure behavior require live nodes.
- Phase 5: the current project Credentials page does not expose Object Storage Access Keys even though current official documentation describes them. Confirm entitlement with Verda or activate the ADR-approved external S3 fallback before relying on off-cluster backup/Loki storage.
- Security posture: no credential, token, coupon, private key, or cloud resource was created, captured, or committed in Phase 0.
