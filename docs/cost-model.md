# Cost and Capacity Model

No price is hard-coded until it is captured from the authenticated Verda account. All estimates must state currency, tax treatment, location, contract type, collection time, and source command.

## Scenarios

| Scenario | Compute intent | Storage intent | Use |
|---|---|---|---|
| Lean | Three nodes at the smallest SKU that safely supports the validated request envelope | Persistent OS storage plus minimum dedicated data disk per node | Fallback when credit is constrained |
| Recommended | Three nodes with headroom for Harbor, monitoring, logs, storage replication, and failure rescheduling | Dedicated data disk per node with replica capacity | Default if budget allows |
| Production target | Dedicated management cluster plus independent workload clusters | Independently sized storage and backup domains | Architecture comparison only; not deployed |

## Required raw inputs

| Input | Unit | Source | Value |
|---|---|---|---|
| Available credit | Currency | Verda console/account status | OPEN |
| Assessment uptime | Hours | Delivery plan | OPEN |
| CPU instance price | Currency/hour/node | `verda instance-types --cpu` | OPEN |
| VM count | Count | Architecture | 3 |
| OS volume price | Currency/GB/month | Verda volume inventory | OPEN |
| Data volume price | Currency/GB/month | Verda volume inventory | OPEN |
| Object-storage capacity price | Currency/GB/month | Verda account/docs | OPEN |
| Object-storage request/egress price | Currency/unit | Verda account/docs | OPEN |
| Public IP or traffic cost | Currency/unit | Verda account/docs | OPEN |

## Formula

For a review window of `H` hours and an average month of `730` hours:

```text
compute = node_count * instance_hourly_price * H
block_storage = total_volume_gb * volume_monthly_price_per_gb * (H / 730)
object_storage = stored_gb * object_monthly_price_per_gb * (H / 730)
traffic_and_requests = measured_or_conservatively_estimated_usage
contingency = 15% * (compute + block_storage + object_storage + traffic_and_requests)
forecast_total = compute + block_storage + object_storage + traffic_and_requests + contingency
```

## Guardrails

- At 70% of available credit: stop bonus expansion and reassess retention and sizing.
- At 85%: stop non-essential workloads and schedule teardown immediately after the agreed review window.
- At 95%: preserve evidence and backups, then stop or hibernate resources according to the approved runbook.
- Spot capacity is never used for etcd/control-plane nodes. It may be considered for an optional worker only.
- Savings claims must include the reliability consequence.

## Capacity acceptance

The selected node flavor must support:

- Loss of one node without making critical platform pods permanently unschedulable.
- Kubernetes and OS reservation before allocatable capacity is calculated.
- Longhorn replica placement and rebuild headroom.
- Explicit Prometheus, Loki, and Harbor retention limits.
- At least 20% steady-state memory headroom in the recommended scenario.
