# Phase 5 Longhorn Reschedule and Integrity

Status: PASS.

The critical storage acceptance drill used a deterministic 4 MiB payload without
recording its checksum value. The workload was deliberately rescheduled, and the
following assertions passed after recovery:

| Assertion | Result |
|---|---:|
| Longhorn nodes | 3 |
| Schedulable dedicated disks | 3 |
| Critical replicas healthy | 3/3 |
| Payload checksum preserved | PASS |
| Persistent storage identities preserved | PASS |
| Test workload and volume cleanup absent | PASS |

The test used only `/var/lib/longhorn` dedicated filesystems; root disks were not
admitted. Available-capacity and one-node-loss scalars are curated separately in
`capacity-before-after.md`.

This result proves replica-backed rescheduling for the Phase 5 critical fixture.
It does not claim application-consistent backup, off-cluster Longhorn recovery,
two-node-loss tolerance, or regional disaster recovery. Those remain owned by the
later backup and restore phase.

PVC, pod, node, volume, replica, disk, and checksum identities remain outside Git.
