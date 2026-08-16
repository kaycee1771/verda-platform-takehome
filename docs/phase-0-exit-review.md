# Phase 0 Exit Review

**Decision:** PASS. Phase 0 is complete. Phase 1 is the only next phase and remains NOT STARTED until explicitly requested; cloud mutation remains prohibited.

**Review date:** 2026-08-16

## Exit-gate evaluation

| Blueprint gate | Result | Evidence | Reason |
|---|---|---|---|
| Actual provider schema inspected | PASS | `evidence/phase-0/provider-schema-summary.md` | Locked provider 1.1.2 re-exported and mechanically enumerated |
| OS image and instance type choices known | PASS | `evidence/phase-0/verda-account-discovery.md` | `CPU.4V.16G`, FIN-03, and exact Ubuntu 24.04 Minimal configuration are pinned |
| Networking limitations documented | PASS | `evidence/phase-0/network-capability-surface.md`, ADR-0005 | Schema, CLI, and current project UI expose no self-service private network/LB/firewall/VIP/DNS; Path B accepted |
| Acceptance matrix complete | PASS | `docs/acceptance-matrix.md` | All R01–R22 have implementation, verification, evidence, and exit contracts |
| Stage A has a credible cost envelope | PASS | `docs/cost.md`, `evidence/phase-0/stage-a-cost-envelope.md` | Seven-day envelope $50.51 vs verified $115.67 balance |

## Verified outcomes

- Provider 1.1.2 exposes eight resources and zero data sources; no resource name was guessed.
- Current project catalog/availability, billing, credential, storage, and network surfaces were inspected read-only.
- Stage A and conditional Stage B remain explicit; no Stage B work is authorized.
- The endpoint strategy is blueprint Path B with an honest default-endpoint SPOF and direct-node recovery.
- Source-of-truth boundaries and manual-operation exceptions are explicit.
- No cloud resource, credential, coupon, key, or secret was created or committed.

## Deferred gates are not Phase 0 failures

| Gate | Blocks | Reason |
|---|---|---|
| GATE-006 Cloud API credential | Phase 2 | Current project has no Cloud API key; Phase 1 is repository-only |
| GATE-007 live WireGuard/MTU/firewall/endpoint tests | Phase 3 | These require the Phase 2 instances; capability absence and Path B are already documented |
| GATE-008 object-storage entitlement or fallback | Phase 5 | Current project does not expose Object Storage Access Keys; no entitlement is assumed |

## Official sources consulted

- Current Verda CLI instances/storage/object-storage, API, public pricing, release notes, and pricing/billing documentation.
- Current Verda Terraform overview/configuration/compute documentation.
- Terraform Registry provider 1.1.2 and exact locally exported provider schema.
- Current RKE2 HA and network/CNI documentation.
- Rancher v2.14 current-version/architecture documentation.

Exact links and discrepancies are in `docs/references.md` and `docs/reports/verda-discovery.md`.

## Rollback

Phase 0 created no cloud resources. Repository changes are documentation, schema-discovery configuration, and read-only tooling. Roll back with a normal Git revert of the Phase 0 commit; do not delete user credentials or account resources.

## Approval boundary

The only next phase is Phase 1 — Repository and quality system. Do not begin Phase 2, create credentials, create instances/volumes, or mutate Verda until the applicable later gate and explicit phase authorization.
