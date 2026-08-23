# Storage and Snapshots

- Three dedicated 100 GiB data volumes back Longhorn.
- Critical storage uses three storage-layer replicas where configured.
- Harbor, Prometheus and Loki persistent claims were Bound during acceptance.
- RKE2 local and off-cluster etcd snapshot procedures are retained.
- Full Velero namespace/PVC restore evidence is not claimed in the mandatory baseline.
