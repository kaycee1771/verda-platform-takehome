# ADR 0006: Bootstrap Argo CD, Then Manage Declaratively

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** GitOps architecture

## Context

Argo CD cannot install itself into an empty cluster without a bootstrap action. Continuing to install platform services imperatively after Argo exists would create two competing sources of truth and make rebuilds non-deterministic.

## Decision

Allow exactly two bootstrap responsibilities after Kubernetes is ready:

1. Install a pinned Argo CD release.
2. Apply a root application pointing at this repository.

Thereafter, Argo CD manages its own desired state, platform components, policies, and environment applications. Use AppProjects, ApplicationSets, sync waves, automated prune, and self-heal.

## Alternatives

- **Helm-install every component from scripts:** easy initially but weakens drift control and recovery.
- **Manual app-of-apps without ApplicationSets:** workable, but repeats environment definitions and obscures promotion structure.
- **Terraform Helm provider:** mixes infrastructure and in-cluster application lifecycles and increases state coupling.

## Consequences

- Git becomes the desired-state audit trail.
- Bootstrap remains intentionally small and testable.
- CRD and controller ordering must be handled through applications and health-aware sync waves.
- Emergency changes must be followed by a Git reconciliation or documented break-glass process.

## Validation

- A clean cluster reaches the intended state from the bootstrap command and repository.
- Manual drift is repaired.
- Reverting a Git commit produces the expected rollback.
