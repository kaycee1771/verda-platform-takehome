# Capacity and Headroom

## Phase 5 pre-change baseline

The protected management API and strict-host-key SSH path were sampled read-only on
2026-08-19 before any Phase 5 mutation. Raw node, pod, endpoint, and filesystem
identity data remains ignored under `.local/`; only aggregate scalars are recorded
here.

| Measure | Aggregate |
|---|---:|
| Ready, schedulable management nodes | 3 |
| Active scheduled pods | 33 |
| Allocatable CPU | 9.000 cores |
| Requested CPU | 3.925 cores (43.61%) |
| Allocatable memory | 39.387 GiB |
| Requested memory | 6.865 GiB (17.43%) |
| CPU request headroom after loss of one equal-sized node | 2.075 cores |
| Memory request headroom after loss of one equal-sized node | 19.393 GiB |
| Root filesystems | 229.35 GiB total, 168.83 GiB available |
| Dedicated Longhorn filesystems | 293.62 GiB total, 293.57 GiB available |

All three dedicated filesystems were mounted, `iscsid` was active, the NFSv4 client
was installed, and mount propagation was available on all three nodes. The
dedicated capacity is the only storage Phase 5 may schedule for Longhorn; root
filesystems are excluded.

## Admission rule

Phase 5 is admitted only if its rendered requests retain a positive one-node-loss
CPU and memory margin and Longhorn reserves enough free space for rebuild and
replica movement. The post-install report must use the same reducer and include
Longhorn schedulable, reserved, and available capacity.

Phase 6 is not admitted merely because Phase 5 fits. Before installing Stage A,
the rendered Phase 6 requests, PVC sizes, replica counts, and peak allowances must
fit the measured post-Phase-5 headroom. Retention and noncritical replicas are
tuned before infrastructure resizing; Stage B remains prohibited until its own
decision gate.

## Measurement semantics

CPU and memory requests use Kubernetes scheduling semantics, including native
restartable init containers and pod overhead. One-node-loss headroom compares the
current requests with two-thirds of the equal-node allocatable aggregate. It is a
capacity margin, not a claim that every application is available after a node
loss; PDBs, placement, storage health, and application behavior remain separate
gates.
