# Management etcd Snapshots

Status: PASS on 2026-08-19.

| Assertion | Result |
|---|---|
| On-demand acceptance snapshot | PASS |
| Local recovery point present | PASS |
| Off-cluster S3-compatible recovery point present | PASS |
| Snapshot compressed | PASS |
| Snapshot ready to use | PASS |
| Positive size | PASS |
| Creation timestamp present | PASS |
| Schedule | Every six hours |
| Local retention | 8 |
| Off-cluster retention | 8 |

The sanitized report records only location classes, not raw paths, bucket names, object names,
endpoints, or credentials. Snapshot credentials were passed through the external process boundary
and applied with secret logging disabled.
