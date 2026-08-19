# Phase 5 Capacity Before and After

Status: PASS for Phase 5 — pre-change and post-change reducers retain positive
one-node-loss scheduling and storage headroom. Phase 6 admission is still pending.

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

The definitive post-install reducer produced:

| Scalar | Value |
|---|---:|
| Nodes Ready/schedulable | 3/3 |
| Requested CPU | 5.935 cores |
| One-node-loss CPU request headroom | 0.065 cores |
| Requested memory | 9.428 GiB |
| One-node-loss memory request headroom | 16.830 GiB |
| Longhorn nodes / schedulable dedicated disks | 3/3 |
| Longhorn available capacity | 314887372800 bytes |
| Worst-two-node available capacity | 209924915200 bytes |

Longhorn uses only the dedicated filesystems; root disks remain excluded. The CPU
margin is positive but narrow. Phase 6 remains blocked until its exact rendered
requests, surge allowance, replica counts, and PVC plan fit this measured result.
