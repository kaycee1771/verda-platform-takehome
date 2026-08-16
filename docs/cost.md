# Phase 0 Cost and Capacity Snapshot

## Status

**BLOCKED — no credible currency value can be calculated yet.** Current CPU prices, storage prices, project balance/credit, and intended review uptime are unavailable because authenticated account discovery cannot run. No numerical daily run rate is fabricated.

## Bounded sizing proposal

These are planning bounds from the authoritative blueprint, not selected Verda resources.

| Stage | Cluster | Count | Candidate CPU shape | Root volume | Data volume | Selection state |
|---|---|---:|---|---:|---:|---|
| A | Management | 3 | `CPU.4V.16G` | 80–100 GiB/node | 100–150 GiB/node | UNVERIFIED against account capacity and price |
| B | Management | 3 | same verified module input | 80–100 GiB/node | 100–150 GiB/node | Conditional on Stage A and credit gate |
| B | Workload | 3 | `CPU.4V.16G` | 60–80 GiB/node | 50–100 GiB/node | UNVERIFIED and not authorized |
| Bonus | GPU worker | 0–1 | account-dependent | account-dependent | account-dependent | Omitted until all core rows are green |

## Required authenticated inputs

| Input | Source | Current value |
|---|---|---|
| Project currency and available credit | `verda cost balance`/console | UNVERIFIED |
| Assessment review window in hours | Candidate delivery plan | UNVERIFIED |
| Selected CPU shape/location/on-demand hourly price | `verda instance-types --cpu` plus availability | UNVERIFIED |
| Exact OS image ID compatible with the shape | `verda images` | UNVERIFIED |
| Root/data NVMe price and minimum size | account inventory/docs | UNVERIFIED |
| Object-storage capacity/request/egress price | account/official price page | UNVERIFIED |
| Public IP/traffic charges | account/official price page | UNVERIFIED |

The installed Verda CLI explicitly describes its cost figures as catalog-based estimates and the web console as billing authority because credits, discounts, and contract terms may differ. The final cost snapshot must reconcile both without recording account identifiers.

## Calculation contract

For `H` review hours and `730` hours per average month:

```text
stage_a_compute = 3 * selected_cpu_hourly_price * H
stage_a_block = stage_a_total_volume_gib * volume_monthly_price_per_gib * (H / 730)
object_storage = forecast_stored_gib * object_monthly_price_per_gib * (H / 730)
traffic_requests = documented conservative estimate or observed usage
subtotal = stage_a_compute + stage_a_block + object_storage + traffic_requests
contingency = 0.15 * subtotal
stage_a_envelope = subtotal + contingency

stage_b_increment = 3 * workload_cpu_hourly_price * H
                    + workload_volume_cost
                    + incremental_object_and_traffic_cost
stage_b_envelope = stage_a_envelope + stage_b_increment + 0.15 * stage_b_increment
```

Phase 0 cost passes only when `stage_a_envelope` is less than the available credit after reserving a teardown/recovery buffer. Stage B needs a separate decision using remaining credit and time.

## Scaling and cut-line triggers

- Sustained node memory above 70% after platform stabilization.
- Prometheus or Harbor OOM/eviction.
- Less than 25% schedulable headroom after requests.
- Longhorn disk use above 60% before evidence collection.
- Forecast reaches 70% of available credit: stop bonus expansion.
- Forecast reaches 85%: stop non-essential workloads and prepare teardown.
- Spot capacity is prohibited for control-plane/etcd nodes.

## Billing risk verified from official documentation

Verda documents prepaid ten-minute billing for pay-as-you-go instances and warns that a zero balance can discontinue instances and delete volumes, with a documented 96-hour volume recovery window. That makes balance monitoring, a minimum 12-hour buffer, and prompt teardown operational controls—not cosmetic cost reporting.

## Current cost impact

- Resources created: 0
- Resources changed: 0
- Cloud run rate introduced by Phase 0: 0
- Stage A daily/monthly forecast: UNVERIFIED; exit gate FAIL
