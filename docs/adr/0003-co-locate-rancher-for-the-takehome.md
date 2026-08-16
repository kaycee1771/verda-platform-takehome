# ADR 0003: Co-Locate Rancher for the Take-Home

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture

## Context

Rancher recommends a dedicated highly available management cluster and discourages user workloads on that cluster. Creating a second three-node management cluster would double the take-home compute footprint before any application environment exists.

## Decision

Install a multi-replica Rancher deployment on the same RKE2 cluster it manages. Label this as a take-home cost optimization and document the dedicated-management-cluster production target.

## Alternatives

- **Dedicated three-node management cluster:** preferred production shape, rejected for the implemented take-home due cost and low incremental assessment value.
- **Single Docker Rancher host:** simpler but explicitly unsuitable as a production pattern and introduces another single point of failure.
- **Documented alternative with no Rancher:** would discard a central assignment requirement without need.

## Consequences

- Rancher remains available when an individual replica or node fails.
- A full local-cluster failure also removes the management plane.
- Rancher and workload resource contention must be monitored and bounded.

## Validation

- Rancher reports the local cluster Active.
- Multiple Rancher replicas are scheduled across nodes.
- An assessor role can view nodes, namespaces, workloads, and health without cluster-admin access.

## Reversal triggers

- The available credit comfortably supports a dedicated management cluster without jeopardizing core scope.
- Co-location prevents the recommended topology from meeting capacity gates.
