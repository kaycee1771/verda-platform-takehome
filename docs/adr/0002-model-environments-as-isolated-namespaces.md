# ADR 0002: Model Environments as Isolated Namespaces

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture and security

## Context

The assignment requires dev, staging, and production with GitOps promotion. Separate clusters provide stronger control-plane and credential isolation but would multiply cost and installation effort. The assignment prioritizes reasoning and an operational end-to-end platform.

## Decision

Implement dev, staging, and production as namespaces on the take-home cluster. Enforce separation with Argo CD projects, RBAC, service accounts, ResourceQuota, LimitRange, restricted Pod Security Admission, and default-deny NetworkPolicies.

Promote a single immutable image digest through reviewed Git changes. Do not rebuild by environment.

The production target architecture retains separate workload clusters, especially for production.

## Alternatives

- **Three physical clusters:** best isolation but excessive for the assessment budget and obscures the promotion demonstration behind repeated bootstrap work.
- **Virtual clusters:** stronger API isolation but adds another control plane and debugging layer that is not required.
- **Only labels in one namespace:** insufficient RBAC, quota, policy, and lifecycle boundaries.

## Consequences

- The take-home clearly demonstrates GitOps promotion and policy boundaries.
- Cluster-admin, CNI, storage, admission, and control-plane failures remain shared.
- Documentation must never describe namespace isolation as equivalent to separate clusters.

## Validation

- Environment service accounts cannot mutate other environments.
- Default-deny traffic tests fail as expected.
- Quota and Pod Security violations are rejected.
- The exact image digest is promoted dev to staging to prod and rolled back through Git.

## Reversal triggers

- Verda explicitly evaluates separate environment clusters.
- Available credits and delivery time make multi-cluster implementation low-risk.
