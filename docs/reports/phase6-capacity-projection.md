# Phase 6 Deterministic Capacity Projection

Status: **BLOCKED — no live or cloud mutation is admitted**

This report covers the ten mandatory Stage A capacity domains at integration
commit `1e65a6a270d85512513cf5287bbfeff44a0d4e11`. The ignored render set is
reproducible with `scripts/phase6/render-capacity-inputs.py`; the tracked
contract binds each render, every checked-in input, and each pinned chart
archive by SHA-256.

## Exact component projection

| Scope | Steady CPU | Peak CPU |
|---|---:|---:|
| Alloy | 150m | 150m |
| Environment foundations | 0m | 0m |
| Harbor and PostgreSQL | 850m | 1050m |
| Monitoring and operators | 600m | 740m |
| Kyverno | 420m | 740m |
| Loki | 275m | 300m |
| Stage A smoke | 40m | 70m |
| Rancher | 1575m | 2100m |
| Sealed Secrets | 50m | 100m |
| Velero with generated work | 500m | 1300m |
| **Total** | **4460m** | **6550m** |

| Scope | Steady memory (bytes) | Peak memory (bytes) |
|---|---:|---:|
| Alloy | 301989888 | 301989888 |
| Environment foundations | 0 | 0 |
| Harbor and PostgreSQL | 1879048192 | 2281701376 |
| Monitoring and operators | 1409286144 | 1811939328 |
| Kyverno | 536870912 | 939524096 |
| Loki | 570425344 | 603979776 |
| Stage A smoke | 67108864 | 117440512 |
| Rancher | 3422552064 | 4563402752 |
| Sealed Secrets | 67108864 | 134217728 |
| Velero with generated work | 1073741824 | 2013265920 |
| **Total** | **9328132096** | **12767461376** |

| Scope | Logical PVC bytes | Raw replicated bytes |
|---|---:|---:|
| Harbor and PostgreSQL | 45097156608 | 122406567936 |
| Monitoring and operators | 12884901888 | 38654705664 |
| Loki | 5368709120 | 16106127360 |
| **Total** | **63350767616** | **177167400960** |

The render inventory contains 350 Kubernetes documents, 34 workload
definitions, and 8 PVC definitions. The one-node-loss retained replica
allocation is 113816633344 bytes.

Prometheus and Alertmanager are operator-generated and therefore cannot be
obtained as StatefulSets from `helm template`. Their checked-in custom-resource
requests, replica counts, reloader resources, and PVC templates are replaced
one-for-one by two projection-only StatefulSets. Velero's three maximum
concurrent data movers and one repository-maintenance worker are modeled as
peak-only projections; they do not inflate steady state.

The Stage A smoke manifests require an immutable Harbor digest and live
readiness gates that do not exist yet. The renderer uses a nonzero synthetic
digest and enables those gates only inside ignored projection output. These
objects are capacity evidence and cannot activate the GitOps tree.

## Baseline and reserves

The retained Phase 5 node and pod JSON reduces in memory to these identity-free
exact values:

- 9000m aggregate allocatable CPU;
- 42291773440 aggregate allocatable memory bytes;
- 6000m worst one-node-loss allocatable CPU;
- 28194512896 worst one-node-loss allocatable memory bytes.
- 7371489280 pre-change requested memory bytes.

The checksum-bound Phase 5 Argo CD, cert-manager, and Longhorn renders add
2751463424 requested memory bytes. The exact post-Phase-5 baseline is therefore
10122952704 bytes. It is 9.427734375 GiB and independently reconciles to the
protected reducer's published 9.428 GiB scalar. Raw and render SHA-256 values
are recorded in the admission contract without exposing node or pod identities.
The protected post-install reducer records 5935m requested CPU; that observed
scalar remains authoritative because Longhorn also creates dynamic workloads.

The explicit operational reserves are:

- 1000m CPU after complete rollout peak and one node loss;
- 4294967296 memory bytes after complete rollout peak and one node loss;
- 53687091200 storage bytes after replicated PVC allocation.

These are conservative take-home reserves for recovery, diagnostics, temporary
snapshots, and bounded growth. They are not estimates of observed use.

## Admission result

CPU blocks the current cluster independently of the missing exact memory input:

- post-Phase-6 steady CPU would be 10395m, exceeding total allocatable CPU by
  1395m;
- post-Phase-6 rollout peak would be 12485m;
- after one node loss the rollout headroom would be negative 6485m;
- including the selected 1000m reserve, the two surviving nodes are short by
  7485m.

Any replacement shape must prove at least 13485m exact worst-two-node
allocatable CPU for this projection and reserve. Marketing vCPU count is not an
acceptable substitute for the rendered Kubernetes allocatable value.

Storage passes the selected reserve:

- total free capacity after replicated PVC allocation: 137719971840 bytes;
- worst-two-node free capacity after retained replicas: 96108281856 bytes.

Candidate-shape memory admission remains indeterminate until a protected read
produces the replacement nodes' exact allocatable bytes. The current baseline
itself is exact and passes the selected memory reserve:

- post-Phase-6 steady memory: 19451084800 bytes;
- post-Phase-6 rollout peak memory: 22890414080 bytes;
- current one-node-loss memory headroom: 5304098816 bytes;
- headroom after the four GiB reserve: 1009131520 bytes.

The candidate shape must satisfy:

```text
worst-two-node allocatable memory >= 27185381376
```

One additional workload-quality blocker is visible: the pinned upstream Rancher
`rancher-pre-upgrade` hook container has no explicit CPU or memory request.
Kubernetes schedules that container at zero request, which the projection
reports exactly. Rancher chart 2.14.3 exposes only image values for this hook;
its template does not consume a resources value or an enable/disable value.
Adding a values key would therefore be inert. Stage A admission remains fail
closed until a supported chart revision, reviewed chart fork, or another tested
rendering mechanism can set the request.

## Candidate-shape thresholds

The current exact thresholds are 9000m and 42291773440 bytes across three
nodes, with 6000m and 28194512896 bytes after the worst node loss. CPU fails;
memory and storage pass.

For an equal three-node replacement, the complete projection plus reserves
requires:

- at least 13485m CPU across the worst two surviving nodes;
- at least 6743m Kubernetes allocatable CPU per node;
- at least 27185381376 memory bytes across the worst two surviving nodes;
- at least 13592690688 Kubernetes allocatable memory bytes per node.

These are Kubernetes allocatable thresholds, not provider vCPU/RAM labels. The
candidate `CPU.8V.32G` shape remains blocked until an exact rendered plan and a
fresh protected node sample prove these values.

## Remaining inputs

1. Fresh protected node and pod JSON after any resize, reduced locally without
   emitting identities.
2. Exact post-resize worst-two-node Kubernetes allocatable CPU and memory.
3. A supported Rancher pre-upgrade hook request mechanism.
4. The real Stage A Harbor digest and live readiness gates.

No cloud API, Kubernetes API, credential, live manifest, Argo root, or live
mutation lease is changed by this projection.
