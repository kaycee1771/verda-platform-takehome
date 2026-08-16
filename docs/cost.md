# Phase 0 Cost and Capacity Snapshot

## Status

**PASS — the selected seven-day Stage A envelope is $50.51 against a verified $115.67 project balance.** Phase 0 created no cloud resources and introduced no run rate.

The envelope deliberately uses on-demand rather than spot capacity for control-plane/etcd nodes, the lean end of the blueprint's storage bounds, a capped allowance for services whose account price is not surfaced, and 15% contingency. Rates must be revalidated immediately before apply.

## Selected bounded sizing

| Stage | Cluster | Count | CPU shape | Location | Root volume | Data volume | State |
|---|---|---:|---|---|---:|---:|---|
| A | Management | 3 | `CPU.4V.16G` | `FIN-03` | 80 GiB/node | 100 GiB/node | Selected for the guaranteed pass path |
| B | Management | 3 | same Stage A cluster | `FIN-03` | unchanged | unchanged | Stage A is retained |
| B | Workload | 3 | `CPU.4V.16G` | revalidate | 60 GiB/node | 50 GiB/node | Planning scenario only; Stage B is not authorized |
| Bonus | GPU worker | 0–1 | account-dependent | account-dependent | account-dependent | account-dependent | Omitted until all core rows are green |

The Stage A 100 GiB data volumes provide 300 GiB raw Longhorn capacity. With three replicas, critical data has roughly 100 GiB usable before filesystem and operational overhead. Loki is intended for off-cluster S3-compatible object storage, and retention/capacity triggers prevent silent disk exhaustion.

## Verified inputs

| Input | Source | Current value |
|---|---|---|
| Project currency and balance | Authenticated Verda console | USD; $115.67 |
| Current project run rate | Authenticated Verda console | $0.00/hour |
| Assessment window | User decision | 168 hours (7 days) |
| Selected CPU shape | Current project deploy catalog | `CPU.4V.16G`: 4 vCPU, 16 GiB RAM |
| Selected location | Current availability list | `FIN-03`; same shape also visible in FIN-01/02 |
| On-demand compute rate | Current project deploy catalog | $0.02790/node-hour |
| Exact image | Current project deploy catalog | Ubuntu 24.04 + Minimal Image; configuration ID `77edfb23-bb0d-41cc-a191-dccae45d96fd` |
| NVMe rate | Console volume quote and current official pricing | $0.20/GiB-month; 50 GiB quoted at $0.01370/hour |
| Object-storage price/entitlement | Current project and official docs | Not surfaced; bounded by allowance and blocked before Phase 5 |
| Public-IP/traffic/request charges | Current project/public price page | No separate rate surfaced; bounded by allowance and must be rechecked before apply |

The CLI has no active Cloud API profile, so the authenticated console is the billing/catalog authority for this snapshot. The CLI/provider are used to corroborate capability boundaries. No account identifier or coupon is recorded.

## Seven-day Stage A calculation

For `H = 168`, three nodes, 540 GiB total NVMe, and 730 hours per average month:

```text
compute = 3 * $0.02790/h * 168h
        = $14.0616

storage = 540 GiB * $0.20/GiB-month * (168h / 730h)
        = $24.8548

known infrastructure subtotal
        = $38.9164

unquoted object/traffic/registry allowance
        = $5.0000

subtotal = $43.9164
15% contingency = $6.5875

calculated envelope = $50.5039
approved planning envelope (rounded up) = $50.51

verified balance = $115.67
remaining after envelope = $65.16
envelope / balance = 43.66%
```

The known VM-plus-NVMe run rate is $0.23165/hour or $5.56/day. A 12-hour infrastructure buffer is $2.78; the remaining balance after the full envelope is materially larger. The $5 allowance is a planning cap, not a fabricated Verda quote: if live object/traffic/registry pricing would exceed it, stop and re-plan before provisioning that service.

## Conditional Stage B scenario

At the lean blueprint bound, three additional workload nodes with 60 GiB root plus 50 GiB data each cost approximately $29.25 for seven days before an incremental $2.50 unquoted-services allowance and 15% contingency. The resulting incremental envelope is $36.51; combined with Stage A it is $87.02. This is planning evidence only. Stage B requires a new decision using actual remaining credit and elapsed review time after Stage A is green.

## Scaling and cut-line triggers

- Sustained node memory above 70% after platform stabilization.
- Prometheus or Harbor OOM/eviction.
- Less than 25% schedulable headroom after requests.
- Longhorn disk use above 60% before evidence collection.
- Forecast reaches 70% of available credit: stop bonus expansion.
- Forecast reaches 85%: stop non-essential workloads and prepare teardown.
- Verified unquoted-services forecast exceeds the $5 Stage A cap: stop and re-plan.
- Spot capacity is prohibited for control-plane/etcd nodes.

## Billing and operating controls

Verda documents prepaid ten-minute billing for pay-as-you-go instances and warns that a zero balance can discontinue instances and delete volumes, with a 96-hour volume recovery window. Reconcile the console balance/rates before apply and at least daily, keep more than 12 hours of run-rate buffer, record the exact creation/expiry timestamps, and tear down deliberately at the approved window.

## Current cost impact

- Resources created: 0
- Resources changed: 0
- Cloud run rate introduced by Phase 0: $0.00/hour
- Selected Stage A known run rate when later provisioned: $0.23165/hour
- Seven-day Stage A planning envelope: $50.51
- Phase 0 cost exit gate: PASS
