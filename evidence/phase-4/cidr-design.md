# Phase 4 CIDR Design

| Purpose | CIDR | Lifecycle |
|---|---|---|
| Management pods | `10.42.0.0/16` | Immutable after first RKE2 start |
| Management services | `10.43.0.0/16` | Immutable; DNS service `10.43.0.10` |
| Future workload pods | `10.44.0.0/16` | Reserved, not implemented |
| Future workload services | `10.45.0.0/16` | Reserved, not implemented |
| Management WireGuard | `10.250.0.0/24` | Existing Phase 3 underlay |

The live pre-installation route gate passed on 2026-08-19. It compared the four planned ranges with
the controller's active LAN, WSL, VMware, and Docker routes and every server's current main route
table. The sanitized result contains 30 observed routes, including 9 explicitly owned resume
routes, no overlap failures, and no raw route or endpoint values.

The planned ranges are pairwise disjoint. RKE2 started only after this check passed, so the
management pod CIDR, service CIDR, cluster DNS, and cluster domain now form an immutable rebuild
boundary.
