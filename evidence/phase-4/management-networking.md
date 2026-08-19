# Management Cluster Networking

Status: PASS on 2026-08-19.

| Test | Observed result |
|---|---|
| Same-node pod paths | 3/3 |
| Cross-node pod paths | 6/6 |
| ClusterIP routing | PASS |
| CoreDNS resolution | PASS |
| Required external egress | PASS |
| NetworkPolicy denial | PASS |
| Internal Traefik routing | PASS on all three nodes |
| Cilium VXLAN payload MTU | 1370 bytes PASS |
| Temporary namespace cleanup | Armed during test and absence proven afterward |

This is Kubernetes networking proof, distinct from the public host-firewall proof. Raw pod, node,
service, and external addresses are intentionally omitted.
