# Cost and Capacity Ledger

## Status

**PASS through the current Phase 5 infrastructure boundary — Stage A infrastructure remains live at
$0.23165/hour ($5.55948/day), excluding unrounded object-storage usage.** The three-node/six-volume
count and provider burn rate reconcile, and Phase 5 added no instance, volume, address, or SSH-key
resource. Object storage is enabled through a documented manual provider-gap exception; its
positive-size byte/request charge remains an explicit operational-ledger residual, is not
represented as zero, and is bounded by the existing $5 unquoted-services allowance. Exact
capacity/operations reconciliation belongs to Phase 14 and does not expand the Phase 4 compute or
block-storage envelope.

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
| Project currency and initial Phase 2 balance | Authenticated Verda CLI | USD; $115.67 |
| Phase 4 project balance | Authenticated Verda CLI at 2026-08-19 13:37Z | $103.01 at that timestamp |
| Current project run rate | Authenticated Verda CLI at 2026-08-19 13:37Z | $0.23165/hour; $5.55948/day |
| Assessment window | User decision | 168 hours (7 days) |
| Selected CPU shape | Current project deploy catalog | `CPU.4V.16G`: 4 vCPU, 16 GiB RAM |
| Selected location | Current availability list | `FIN-03`; same shape also visible in FIN-01/02 |
| On-demand compute rate | Current project deploy catalog | $0.02790/node-hour |
| Exact image | Current project deploy catalog | Ubuntu 24.04 + Minimal Image; configuration ID `77edfb23-bb0d-41cc-a191-dccae45d96fd` |
| NVMe rate | Console volume quote and current official pricing | $0.20/GiB-month; 50 GiB quoted at $0.01370/hour |
| Object-storage price/entitlement | Current project and official docs | Entitlement enabled manually; positive-size byte/request charge is unmeasured, covered by the $5 allowance, and reconciled exactly in Phase 14 |
| Public-IP/traffic/request charges | Current project/public price page | No separate rate surfaced; bounded by allowance and must be rechecked before apply |

The time-bound project credential remained process-only. The authenticated CLI and provider were used for the final account, resource, rate, catalog, and drift reconciliation. No account identifier, credential value, or coupon is recorded.

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

The known VM-plus-NVMe run rate is $0.23165/hour or $5.55948/day. A 12-hour infrastructure buffer is $2.78; the remaining balance after the full envelope is materially larger. The $5 allowance is a planning cap, not a fabricated Verda quote: if live object/traffic/registry pricing would exceed it, stop and re-plan before provisioning that service.

## Phase 6 mandatory capacity candidate

The complete rendered Stage A workload does not fit the current three
`CPU.4V.16G` nodes with the required one-node-loss reserve. A read-only,
authenticated provider preflight at `2026-08-20T05:54:40Z` confirmed that
`CPU.8V.32G` was available in `FIN-03` at `$0.0558/instance-hour`; the provider
reported a `$99.22` balance and the unchanged `$0.23164521/hour` current burn at
that instant. These facts are time-bound and must be refreshed before each
replacement.

Replacing the three compute instances while preserving all six volume resources
would raise the known rate to `$0.31534521/hour`. The seven-day known subtotal is
`$52.97799528`; adding the existing `$5` unquoted-services allowance and 15%
contingency gives `$66.674694572`. Including the mandatory 12-hour reserve gives
a maximum exposure of `$70.458837092`, approximately 71.01% of the authenticated
balance. This exceeds the currently approved `$50.51` Stage A envelope and the
70% bonus-expansion cut line. It is therefore **not authorized** by the prior
cost decision: no replacement may occur until the user approves an exact new
ceiling and evaluator expiry. Stage B and GPU expansion remain frozen.

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

- Resources created by Phase 2: 3 CPU instances, 3 instance-owned 80 GiB OS volumes, 3 protected 100 GiB data volumes, and 1 SSH-key record
- Resources changed after creation: server-02 compute and its instance-owned OS disk were replaced once through the explicitly authorized, exact saved plan; all three persistent data volumes were preserved
- Cloud run rate introduced by Phase 2: $0.23165/hour or $5.55948/day
- Balance at final 2026-08-17 reconciliation: $115.40
- Balance at the 2026-08-19 13:37Z authenticated reconciliation: $103.01; this value is
  timestamp-bound and is not presented as the current balance after that instant
- Seven-day Stage A planning envelope: $50.51
- Known infrastructure seven-day cost: $38.92; 15% contingency: $44.75
- Phase 3 resource delta: none; the live preflight again reconciled 3 instances, 6 volumes, zero drift, and the expected hourly rate
- Phase 2 cost gate: PASS; Phase 3 cost gate: PASS
- Phase 4 pre-installation reconciliation: exactly 3 instances and 6 volumes, zero Terraform drift,
  $0.23165/hour infrastructure run rate, and a seven-day infrastructure-plus-contingency projection
  of $44.75385
- Phase 4 resource delta: none; RKE2, Cilium, Traefik, and host configuration add no Verda compute or
  block-volume resource
- Phase 4 object-storage delta: one manually managed snapshot bucket with a positive-size recovery
  point; its unmeasured byte/request charge is a separately tracked provider-billing residual, is not
  rounded to zero, and remains inside the $5 unquoted-services allowance pending exact Phase 14
  capacity/operations reconciliation
- Phase 4 infrastructure cost gate: PASS; the guarded bootstrap rechecked the unchanged three-node
  resource envelope before mutation, and Phase 4 created no additional compute or block volumes
- Phase 5 resource delta: none; Argo CD, cert-manager, Longhorn, certificates, and ingress use the
  existing three instances, six volumes, three addresses, and registered key boundary
- Phase 5 known infrastructure run rate: unchanged at `$0.23165/hour` or `$5.55948/day`; the
  object-storage positive-size capacity/request residual remains unmeasured, is not represented as
  zero, and stays inside the existing `$5` allowance pending Phase 14 reconciliation
