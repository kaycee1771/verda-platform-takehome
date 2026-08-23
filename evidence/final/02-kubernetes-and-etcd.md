# Kubernetes and etcd

Read-only live result:

| Node | Ready | Allocatable CPU | Allocatable memory |
|---|---|---:|---:|
| verda-mgmt-server-01 | True | 3 | 13,766,856 Ki |
| verda-mgmt-server-02 | True | 3 | 13,766,848 Ki |
| verda-mgmt-server-03 | True | 3 | 13,766,856 Ki |

The Kubernetes `/readyz?verbose` path passed and includes the etcd readiness check. All three nodes are schedulable RKE2 server/etcd members.
