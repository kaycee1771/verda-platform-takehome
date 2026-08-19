# Phase 5 Capacity Before and After

Status: PARTIAL — pre-change baseline PASS; post-change and Phase 6 admission are
pending.

The identity-free pre-change reducer produced:

| Scalar | Value |
|---|---:|
| Nodes Ready/schedulable | 3/3 |
| Active scheduled pods | 33 |
| Allocatable CPU | 9.000 cores |
| Requested CPU | 3.925 cores |
| Allocatable memory | 39.387 GiB |
| Requested memory | 6.865 GiB |
| One-node-loss CPU request headroom | 2.075 cores |
| One-node-loss memory request headroom | 19.393 GiB |
| Dedicated data capacity available | 293.57 GiB |
| Root capacity available | 168.83 GiB |

Longhorn may use only the dedicated filesystems. A post-install sample using the
same scheduling-aware reducer must record platform overhead, Longhorn reserved and
available capacity, root-disk exclusion, and one-node-loss margin. Phase 6 remains
blocked until its exact rendered requests and PVC plan fit that measured result.
