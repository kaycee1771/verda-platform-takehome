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

## Phase 5 post-change result

The definitive protected-main sample after Argo CD, cert-manager, authenticated
ingress, and Longhorn convergence produced:

| Measure | Aggregate |
|---|---:|
| Ready, schedulable management nodes | 3 |
| Requested CPU | 5.935 cores |
| CPU request headroom after loss of one equal-sized node | 0.065 cores |
| Requested memory | 9.428 GiB |
| Memory request headroom after loss of one equal-sized node | 16.830 GiB |
| Longhorn nodes / schedulable dedicated disks | 3 / 3 |
| Longhorn available capacity | 314887372800 bytes (293.262 GiB) |
| Worst two-node available capacity | 209924915200 bytes (195.508 GiB) |

The margins are positive but CPU is intentionally tight. This result admits
Phase 5; it does not admit Phase 6. Phase 6 must fit its exact rendered requests,
replica counts, PVCs, and operational surge allowance without consuming the
0.065-core one-node-loss CPU margin.

## Admission rule

Phase 5 was admitted only because its rendered requests retained a positive one-node-loss
CPU and memory margin and Longhorn reserves enough free space for rebuild and
replica movement. The post-install report must use the same reducer and include
Longhorn schedulable, reserved, and available capacity.

Phase 6 is not admitted merely because Phase 5 fits. Before installing Stage A,
the rendered Phase 6 requests, PVC sizes, replica counts, and peak allowances must
fit the measured post-Phase-5 headroom above. Retention and noncritical replicas are
tuned before infrastructure resizing; Stage B remains prohibited until its own
decision gate.

## Measurement semantics

CPU and memory requests use Kubernetes scheduling semantics, including native
restartable init containers and pod overhead. One-node-loss headroom compares the
current requests with two-thirds of the equal-node allocatable aggregate. It is a
capacity margin, not a claim that every application is available after a node
loss; PDBs, placement, storage health, and application behavior remain separate
gates.
