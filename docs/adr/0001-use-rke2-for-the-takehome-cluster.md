# ADR 0001: Use RKE2 for the Take-Home Cluster

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture

## Context

The assignment permits k3s, kubeadm, or RKE2 and requires Rancher or a justified alternative. The platform must demonstrate availability, hardening, systematic operations, and understandable failure behavior on manually provisioned VMs.

## Decision

Use a pinned RKE2 release compatible with the selected Rancher version. Run three server nodes with embedded etcd; each node also carries the worker role to fit the take-home budget. Enable the RKE2 CIS profile after satisfying its host prerequisites.

## Alternatives

- **k3s:** lower resource cost and operationally attractive, but provides less opportunity to demonstrate the hardened Rancher-aligned distribution expected in this assignment.
- **kubeadm:** maximizes upstream transparency but creates substantially more bootstrap and lifecycle work without improving the assessment outcome.
- **Single-node RKE2:** cheapest, but cannot substantiate quorum or node-failure claims.

## Consequences

- Three nodes provide etcd quorum and a meaningful failure drill.
- Co-locating worker roles makes node pressure a real risk that must be controlled with capacity, reservations, and priorities.
- A stable API/registration endpoint remains separate from etcd HA and must be designed honestly.
- Version selection is incomplete until the Rancher support matrix is checked.

## Validation

- All three nodes are Ready.
- etcd health and member list are healthy.
- A one-node shutdown does not break API availability or replicated application service.
- CIS self-assessment results and exceptions are recorded.

## Reversal triggers

- No three-node CPU topology fits the available credit.
- The selected Verda VM/network behavior is incompatible with supported RKE2 networking.
- A supported managed Kubernetes option is explicitly required by updated assignment guidance.
