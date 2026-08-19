# Management Firewall and Public-Port Boundary

Status: PASS on 2026-08-19 from the approved administrator source.

## Proven controls

- The dedicated host table retains default-drop input and forward policies.
- Public Kubernetes API access is restricted to approved administrator sources.
- RKE2 supervisor, etcd, kubelet, Cilium, metrics, HTTP/S, and NodePort paths remain excluded from
  the public allow rules.
- Internode control-plane and overlay traffic is restricted to the exact WireGuard peer boundary.
- Cilium pod forwarding uses only the required interfaces, management pod CIDR, established state,
  and the documented proxy mark. There is no global forward accept.
- Every changed firewall was applied atomically under a five-minute rollback timer and retained
  only after a fresh strict administrator session succeeded.
- All three nodes accepted the intended administrator SSH and Kubernetes API ports.
- All three nodes denied the source-controlled supervisor, etcd, kubelet, Cilium, metrics, HTTP/S,
  and representative low, middle, and high NodePort probes.
- The curated result records three nodes, allowed port classes, denied port classes, and no endpoint
  values.

## Residual limitation

The current single-controller environment cannot provide a genuinely independent non-allowlisted
source. The exact nftables default-drop contract and approved-source negative scan are proven; a
second-vantage scan remains desirable when another controlled source is available.
