# External Port-Scan Evidence

## Result

**PASS from the approved administrative path on all three public endpoints.** Endpoint values are
redacted.

| Port or range | Intended Phase 3 state | Observed on every node |
|---|---|---|
| TCP 22 | Open only from approved administrator `/32` | Open |
| TCP 80, 443 | Closed until Phase 5 ingress | Filtered or closed |
| TCP 2379–2381 | Internal etcd only in Phase 4 | Filtered or closed |
| TCP 4240 | Internal Cilium health only in Phase 4 | Filtered or closed |
| TCP 6443 | Kubernetes API closed until Phase 4 | Filtered or closed |
| TCP 9090 | Internal metrics only in later phase | Filtered or closed |
| TCP 9345 | Internal RKE2 supervisor only in Phase 4 | Filtered or closed |
| TCP 10250 | Internal kubelet only in Phase 4 | Filtered or closed |
| TCP 30000, 31000, 32767 | Sampled NodePort boundary | Filtered or closed |

The live mesh independently proves UDP 51820 works only between the exact node peer endpoints. The
host-owned `inet verda_platform` table uses default-drop input/forward policies, accepts established
traffic, rate-limits new allowed SSH sessions, and does not replace the complete machine ruleset.

This proves etcd is not reachable from the public internet-facing path before etcd exists; Phase 4
must repeat the scan after RKE2 binds its services.
