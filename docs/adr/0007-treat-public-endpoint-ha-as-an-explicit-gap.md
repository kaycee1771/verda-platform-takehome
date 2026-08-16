# ADR 0007: Treat Public Endpoint HA as an Explicit Gap

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Network architecture
- **Blocking gate:** GATE-003

## Context

Three control-plane nodes create etcd and process redundancy, but they do not automatically provide a stable highly available Kubernetes API or public ingress address. Current provider discovery has not yet proven a managed load balancer, floating IP, or health-aware DNS capability.

## Decision

Do not claim endpoint HA until an external endpoint is verified. Run ingress capacity across nodes, restrict administrative ports, and select the strongest available endpoint strategy after discovery.

Preferred order:

1. Managed or externally hosted health-checked L4 load balancer.
2. Health-aware multi-record DNS with documented client behavior.
3. A designated ingress/API endpoint with an explicit single-point-of-failure statement and tested recovery runbook.

## Alternatives

- **kube-vip/keepalived:** requires network semantics such as L2 adjacency or movable addresses that have not been proven.
- **Unqualified DNS round-robin:** distributes traffic but is not health-aware HA by itself.
- **Expose every NodePort:** rejected due unnecessary attack surface and poor assessor ergonomics.

## Consequences

- Availability statements remain accurate.
- The take-home may have HA control-plane data but a non-HA external access path.
- DNS, TLS SANs, certificates, firewall rules, and access documentation depend on the selected endpoint.

## Validation

- Endpoint behavior is tested while the active ingress/API node is unavailable.
- Certificate and DNS resolution remain valid for the selected strategy.
- The documented recovery time matches the observed result.

## Reversal triggers

- Account discovery confirms a supported managed load balancer or floating endpoint.
- Verda support documents a platform-native HA pattern for these CPU VMs.
