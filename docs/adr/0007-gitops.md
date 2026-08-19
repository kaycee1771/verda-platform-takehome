# ADR 0007: Bootstrap Argo CD Minimally and Keep Git Authoritative

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** GitOps architecture
- **Blocking gates:** Phase 5 live, local, and hosted closeout gates are closed; Phase 6 capacity and acceptance remain

## Context

Argo CD cannot install itself into an empty cluster. Installing platform services imperatively after Argo exists would create competing desired-state owners.

## Decision

Bootstrap only a pinned Argo CD release and one root Application. Use restricted AppProjects and ApplicationSets for platform/services/environments, automated prune/self-heal, and explicit sync waves. Production promotion approval occurs through protected Git review; rollback is Git revert.

## Alternatives considered

- **Imperative Helm scripts:** quick but weakens drift/recovery proof.
- **Terraform Helm provider:** couples infrastructure and in-cluster state.
- **Permissive default Argo project:** rejected due excessive source/destination/resource scope.

## Consequences

- Git is the desired-state and promotion audit trail.
- CRD/controller ordering and bootstrap credentials require deliberate handling.
- Emergency cluster changes require immediate Git reconciliation or rollback documentation.

## Validation evidence

Phase 5 used the two-action boundary with Argo CD chart 10.3.3 / application v3.5.1. The idempotent
replay reached Helm revision 5 and retained exactly one root Application. The root owns an exact
eight-child set, and all nine Applications were Healthy and Synced. Git admitted the staging
certificate, then production certificate, then authenticated TLS ingress in separate protected
changes. The converged-ingress lifecycle verifier rejects extra, foreign, or mutated ingress
resources while retaining the zero-ingress day-zero state.

Application release drift, bad-digest rollback, and promotion reversal remain later-phase proofs;
they are not inferred from the Phase 5 platform-bootstrap result.

## Production evolution

Add SSO, multi-tenant project controls, policy checks, controlled sync windows, notifications, and isolated repository/cluster credentials.
