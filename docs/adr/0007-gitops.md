# ADR 0007: Bootstrap Argo CD Minimally and Keep Git Authoritative

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** GitOps architecture
- **Blocking gates:** Exact Argo CD version remains pending Phase 1 lock review

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

A clean cluster must converge from the two bootstrap actions; Application inventory must be Healthy/Synced; manual drift self-heals; bad desired state is visible; Git revert restores the prior digest.

## Production evolution

Add SSO, multi-tenant project controls, policy checks, controlled sync windows, notifications, and isolated repository/cluster credentials.
