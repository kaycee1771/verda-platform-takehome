# Phase 6 monitoring desired state

This subtree defines the offline desired state for
`kube-prometheus-stack` chart `88.3.0` with Prometheus Operator `v0.93.0`.
It is not yet admitted into the Argo root.

The selected lean Platform profile retains stock dashboards and rules for the
enabled RKE2-compatible targets. It runs one Prometheus replica with three-day,
six-GB retention on a 10-GiB `longhorn-critical` claim and one Alertmanager
replica with a 2-GiB claim. This is storage replication and rescheduling, not
application-level HA. Grafana is stateless because its data sources and
dashboards are Git-provisioned.

Prometheus and Alertmanager remain ClusterIP-only, without Ingress, per-replica
services, routes, or external Thanos services. Grafana is also internal until a
separate staging-first certificate and authenticated ingress boundary is
admitted. The referenced `grafana-admin-credentials` Secret must be supplied by
the approved Sealed Secrets flow; plaintext is never stored here.

`image-lock.yaml` inventories every enabled workload image resolved from the
exact chart render. The registry manifests were locked on 2026-08-20 and the
values render those immutable references. The component still must not enter
the root Application until the reviewed security exceptions, Secrets, and
capacity admission pass.

The chart's required Prometheus Operator cluster RBAC and node-exporter
read-only host mounts trigger six HIGH/CRITICAL findings in the pinned Trivy
ruleset after all avoidable findings are removed. They have no blanket ignore
here. Integration must add a resource-identity-scoped, reviewed exception and
prove that the exception matches only those exact capabilities.

The objects under `resources/` are post-controller resources. They must be
owned separately from the controller chart and synchronized only after the
Prometheus Operator CRDs exist.
`capacity/operator-workloads.capacity-input` models the Prometheus and
Alertmanager StatefulSets that the operator generates. Its non-manifest suffix
keeps the reducer input outside Kubernetes desired-state discovery; it must
never be applied to Kubernetes.
