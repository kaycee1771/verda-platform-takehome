# Capacity

The platform uses three equal RKE2 nodes, each with 3 allocatable CPU cores and about 13.1 GiB allocatable memory. The mandatory stack was right-sized before deployment: Rancher uses one replica, Prometheus one replica with critical priority, bounded Loki retention, small PVCs, and lower-criticality controllers use one replica. The application uses 10m CPU/16Mi memory requests per replica and production runs two replicas.

| Measure | Current result |
|---|---:|
| Ready schedulable nodes | 3 |
| Aggregate allocatable CPU | 9 cores |
| Aggregate allocatable memory | about 39.4 GiB |
| Longhorn raw dedicated capacity | 300 GiB |
| Application replicas | dev 1, staging 1, prod 2 |
| Prometheus active/up targets | 46 / 42 |

The cluster is intentionally dense: temporary Rancher/Fleet jobs can cause scheduling delay during rollouts. Critical platform pods have priorities and all mandatory steady-state pods were Ready at acceptance. Losing one node preserves etcd quorum but reduces workload headroom materially; upgrades and disruptive work must remain serial.
