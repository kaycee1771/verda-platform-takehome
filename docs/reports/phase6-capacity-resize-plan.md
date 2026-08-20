# Phase 6 Capacity Resize Decision

Status: **APPROVED BOUNDARY — provider preflight passed; live mutation remains fail closed**

## Trigger

The Phase 5 cluster exposes 9.000 allocatable CPU cores and currently requests
5.935 cores. Scheduling against the two-node failure-domain budget therefore
leaves only 0.065 cores. The conservative Rancher, Harbor/Trivy, and temporary
Stage A application baseline alone adds approximately 3.025 requested cores;
the monitoring, logging, policy, secret, and backup controllers add more. A
resize-free Phase 6 deployment is not admissible.

## Candidate shape and cost

The [official Verda public catalog](https://verda.com/pricing?currency=usd),
rechecked on 2026-08-20, lists `CPU.8V.32G` with 8 vCPU, 32 GiB memory, and an
on-demand price of `$0.0558` per instance-hour. An authenticated console and
provider-CLI preflight at `2026-08-20T05:54:40Z` independently confirmed that
the exact on-demand shape was available in `FIN-03` at `$0.0558/hour`. The
provider API reported three current instances, six volumes, a reconciled
`$0.23164521/hour` burn rate, and a `$99.22` balance. The ignored sanitized
preflight records only these aggregate scalars and no resource identifiers or
endpoints. Availability, price, and balance must still be refreshed immediately
before each saved-plan apply because they are time-varying provider facts.

Replacing all three current `CPU.4V.16G` instances with the candidate changes
the compute portion from `$0.08370/hour` to `$0.16740/hour`. Keeping the current
volume model unchanged produces a known infrastructure planning rate of
`$0.31535/hour` or `$7.56840/day`, excluding measured-positive but currently
unitemized object-storage charges.

For seven days, the known compute plus NVMe estimate becomes `$52.97799528`.
Adding the existing `$5` unquoted-services allowance and 15% contingency
produces a planning envelope of `$66.674694572`. Adding the required 12-hour
reserve at the candidate rate produces a maximum exposure of `$70.458837092`.
Against the authenticated `$99.22` balance, that is approximately 71.01% and
therefore crosses the 70% expansion trigger. On 2026-08-20 the user explicitly
approved the mandatory Phase 6 resize within a maximum seven-day envelope of
`$70.46` and evaluator expiry `2026-08-27T21:00:00Z`. Stage B and GPU remain
frozen. A fresh authenticated balance, price, and availability check is still
required before each saved-plan apply.

## Replacement semantics

The pinned
[Verda Terraform provider](https://github.com/verda-cloud/terraform-provider-verda/tree/v1.1.2)
`v1.1.2` at commit
`8f3dd283d9d956107cabbd7df4641d607e477d4c` applies
`RequiresReplace` to `verda_instance.instance_type`; its update method also
states that instances cannot be updated. The resize is therefore a controlled
three-node replacement, not an in-place change.

The dedicated Longhorn data volumes are independent Terraform resources and
must remain preserved and reattached. The instance-owned OS disk and public
address are replacement-scoped. Regenerated inventory, WireGuard membership,
RKE2/etcd membership, host firewall addressing, direct kubeconfigs, TLS SANs,
and sslip.io endpoint documents must converge to the observed replacement
addresses after each node.

## Admission gates

No replacement may begin until all of the following are true:

1. Every Phase 6 chart and image is checksum or digest locked.
2. The complete rendered Stage A workload has an exact scheduling request,
   PVC, rollout-surge, and one-node-loss model.
3. The candidate's observed Kubernetes allocatable value is at least 6793m CPU
   and 13659799552 memory bytes per node, so the complete model remains
   positive after one node loss and leaves the documented operational reserve.
4. An authenticated catalog check proves shape availability and current price.
5. A fresh balance check proves the seven-day envelope plus the 12-hour reserve.
6. Terraform produces a saved, sanitized, reviewed plan scoped to one compute
   instance and its instance-owned OS disk, with the dedicated data volume
   explicitly unchanged.
7. Current etcd and off-cluster recovery points are healthy and timestamped.
8. The security and reliability reviewers approve the exact plan and rollback.
9. The single-writer live-mutation lease explicitly enables Phase 6 writes.

## Serial execution and abort boundary

Replace one node at a time, with the designated primary last. A replacement is
not complete merely because the VM is running. Before another replacement, the
cluster must return to three active RKE2 services, three Ready nodes, three
healthy etcd members with no alarms, healthy Cilium/Hubble, healthy Longhorn,
all Phase 5 Argo Applications Healthy/Synced, and zero unexpected unhealthy
workloads. The new node must show the intended allocatable CPU and memory and
the preserved data-volume identity.

After every replacement, regenerate and converge inventory and host/RKE2
configuration, verify all direct API paths, update the accepted named endpoint
and certificate path where required, and rerun the bounded one-node recovery
checks. Never replace or stop a second server while the first is absent or
degraded.

Abort the sequence on an unplanned Terraform action, missing volume identity,
etcd/member mismatch, API loss, Cilium or Longhorn degradation, failed endpoint
reconciliation, unexpected cost, or failure to restore the full three-node
baseline within the defined window. Preserve the two-node quorum, the dedicated
data volumes, off-cluster recovery material, the saved plan, and sanitized
diagnostics. Do not continue to another node to "see if it fixes itself."

## Capacity decision

The checksum-bound complete projection now requires 13585m CPU and
27319599104 memory bytes across the worst two surviving nodes, including the
selected 1000m CPU and four-GiB operational reserves. The RKE2 configuration
pins 500m kube-reserved plus 500m system-reserved CPU per node, so an exact
8-vCPU candidate is expected to expose 7000m allocatable CPU. That would leave
415m beyond the declared CPU reserve across the surviving pair. This is a
planning inference only: admission remains closed unless the protected node
reducer observes at least the thresholds above after each replacement.

## Remaining decision inputs

- Exact Terraform single-node replacement plans from the integrated resize
  controller and a fresh balance/availability recheck immediately before each
  apply.
- Fresh identity-free per-node allocatable CPU/memory after the first candidate
  boots; abort if the minimum is below the capacity contract.
- Reviewed endpoint/certificate reconciliation sequence for the primary node.
