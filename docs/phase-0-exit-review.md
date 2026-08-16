# Phase 0 Exit Review

**Decision:** BLOCKED. Phase 1 and all cloud mutation remain prohibited.

**Review date:** 2026-08-16

## Exit-gate evaluation

| Blueprint gate | Result | Evidence | Reason |
|---|---|---|---|
| Actual provider schema inspected | PASS | `evidence/phase-0/provider-schema-summary.md` | Locked provider 1.1.2 re-exported and mechanically enumerated |
| OS image and instance type choices known | FAIL | `evidence/phase-0/verda-account-discovery.md` | Authenticated images/types/availability unavailable |
| Networking limitations documented | FAIL | `docs/reports/verda-discovery.md`, ADR-0005 | Provider limitations are known; current account/API/console capabilities are not |
| Acceptance matrix complete | PASS | `docs/acceptance-matrix.md` | All R01–R22 have implementation, verification, evidence, and exit contracts |
| Stage A has a credible cost envelope | FAIL | `docs/cost.md` | No current account prices, currency, credit balance, or review window |

## Verified repository-side outcomes

- No provider resource name was guessed; provider 1.1.2 exposes eight resources and zero data sources.
- Stage A and Stage B are explicit; the earlier single-cluster-final assumption is corrected in ADR-0002.
- Initial ADRs cover distribution, topology, role layout, CNI, endpoints, storage, GitOps, registry/supply chain, secrets, observability, and recovery.
- Source-of-truth boundaries and manual-operation exceptions are explicit.
- Raw account/schema output is ignored; no resource or secret was created, requested, or printed.

## Exact blocker

Neither `VERDA_CLIENT_ID` nor `VERDA_CLIENT_SECRET` is available to the current shell or active Verda CLI profile. Read-only account queries for locations, CPU types/prices, images, availability, volumes, account status, running cost, and balance fail with `AUTH_ERROR`. The in-app browser and connected Chrome session both redirect to the Verda sign-in page, so no authenticated console state exists to use as a read-only fallback.

## Official sources consulted

- Current Verda CLI instances/storage/object-storage and pricing/billing documentation.
- Current Verda Terraform overview/configuration/compute documentation.
- Terraform Registry provider 1.1.2 page and exact locally exported provider schema.
- Current RKE2 HA and network/CNI documentation.
- Rancher v2.14 current-version/architecture documentation.

Exact links and recorded discrepancies are in `docs/references.md` and `docs/reports/verda-discovery.md`.

## Resolution alternatives

| Option | Tradeoff | Recommendation |
|---|---|---|
| Configure least-privilege Verda API credentials locally, confirm credit, rerun `make phase0-discover-account` | Most reproducible and closes account gates without exposing values; requires user-controlled credential setup | **Recommended** |
| User performs console inspection and supplies sanitized exports/screenshots | Can reveal console-only network features, but is less machine-verifiable and still needs CLI/provider correlation | Supplemental only |
| User runs the repository discovery target in another authenticated shell and copies only the ignored JSON locally | Preserves command behavior but increases handoff/sanitization risk and weakens direct reproducibility | Fallback |

## Rollback

Phase 0 created no cloud resources. Repository changes are documentation, schema-discovery configuration, and read-only tooling. Roll back by reverting the Phase 0 commit; preserve the blueprint input outside Git and do not delete user credentials or account resources.

## Approval boundary

The only permitted next action is credential setup outside the repository followed by authenticated read-only discovery. Do not begin Phase 1, create instances, create volumes, or mutate any Verda resource.
