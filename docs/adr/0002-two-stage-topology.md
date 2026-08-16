# ADR 0002: Deliver Stage A Before the Two-Cluster Gold Target

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture and delivery
- **Blocking gates:** Stage B requires its own credit/time/readiness gate

## Context

The original Phase 0 baseline treated a co-located three-node cluster as the final take-home topology. The authoritative blueprint instead requires a guaranteed end-to-end pass path before introducing a separate management/workload failure domain.

## Decision

Implement Stage A on one three-node `verda-mgmt` cluster with platform services and `demo-dev`, `demo-staging`, and `demo-prod`. Only after every mandatory Stage A row is green, create `verda-workload` from the same modules and migrate the three environment namespaces there. Rancher and Argo CD then manage both clusters.

## Alternatives considered

- **One cluster as final:** cheapest and simplest, but weakens the Rancher/multi-cluster and independent-failure-domain story.
- **Six nodes immediately:** strong target shape, but risks losing the mandatory end-to-end path to cost/time/complexity.
- **Separate dev/staging/prod clusters:** stronger isolation but disproportionate cost for this assignment.

## Consequences

- Stage A is explicitly temporary co-location, not a production claim.
- Stage B demonstrates reusable modules and management/workload independence.
- If Stage B cannot be completed rigorously, the submission retains a proven Stage A and honestly documents Stage B as designed-only.
- Environments remain namespaces within the workload cluster; production evolution requires stronger production isolation.

## Validation evidence

Stage B is prohibited until the Stage A acceptance matrix is green, clean rebuild works, CI-to-dev GitOps works, alert/log proof exists, secret scans are clean, and remaining credit/time has contingency.

## Production evolution

Use dedicated management and workload clusters, normally isolate production in a separate cluster/project/account, and expand worker pools independently of control-plane nodes.
