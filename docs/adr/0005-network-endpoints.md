# ADR 0005: Discover Secure Node Networking and Stable Endpoints Before Implementation

- **Status:** Proposed
- **Date:** 2026-08-16
- **Owners:** Network and security architecture
- **Blocking gates:** GATE-001, GATE-003

## Context

Public VM IPs are required, but no current account evidence proves a private network, managed L4 load balancer, floating IP, security group, or private VIP. Provider 1.1.2 exposes none of those resource types. RKE2 HA still requires a fixed registration address.

## Decision

Prefer Path A: verified Verda private node networking plus a supported HA API/ingress endpoint. If unavailable, use Path B: a host WireGuard mesh for internode traffic, a documented primary registration/API endpoint, direct-node break-glass kubeconfigs, and ingress on multiple nodes. DNS round robin without health checking is never called a highly available load balancer.

## Alternatives considered

- **kube-vip/Keepalived:** only if observed L2/L3 semantics support movable/private virtual IPs.
- **Unqualified public IP mesh:** rejected due avoidable plaintext/control-plane exposure.
- **Single endpoint with no break glass:** rejected because endpoint loss would make recovery unnecessarily opaque.

## Consequences

- This ADR cannot be Accepted until authenticated account/API/console discovery closes the network unknowns.
- TLS SANs, firewall rules, RKE2 registration, DNS, ingress, and evaluator access depend on the selected path.
- A non-HA endpoint may remain an honest residual risk even with HA etcd.

## Validation evidence

Required evidence: account capability inventory, selected endpoint diagram, MTU, peer/port matrix, client and server registration behavior, primary-endpoint failure test, and direct-node recovery path.

## Production evolution

Use a managed health-checked L4 endpoint, private networking, managed firewall controls, and DNS automation across independent failure domains.
