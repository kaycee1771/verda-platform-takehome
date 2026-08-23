# Alloy Phase 6 collection boundary

This directory defines chart `1.11.1` with Alloy `v1.18.1` as a three-node
DaemonSet. Alloy discovers pod targets and tails container logs through the
Kubernetes API. Discovery is restricted to `spec.nodeName` for the current
DaemonSet pod, while clustered source ownership provides an additional
duplicate-collection guard. Kubernetes events are collected once through the
same clustered ownership mechanism.

The collector intentionally does not mount `/var/log`, container-runtime log
directories, `/var/log/journal`, `/run/log/journal`, or any RKE2 journald
location. RKE2 service journals remain available through the Phase 4
break-glass path until a separate access, privacy, capacity, and retention
decision authorizes collection.

RBAC is limited to `get`, `list`, and `watch` on namespaces, pods, pod logs,
and events. Alloy cannot read Secrets, ConfigMaps, nodes, workloads, or custom
resources. Its service-account token is mounted because Kubernetes API log and
event collection requires it. Chart `1.11.1` emits invalid YAML for an explicit
empty `clusterRules` list, so the values include one duplicate pod-read rule;
the rendered ClusterRole gains no additional resource or verb.

Indexed labels are bounded to cluster, namespace, environment, application,
container, and normalized JSON log level. Pod name, request ID, and release
version are retained as structured metadata instead of indexed labels. The
write client has bounded streams, batches, retries, and backoff.

`image-lock.yaml` is deliberately blocked even though its registry-resolved image
digest is now locked. Do not create the wave `-6` Argo Application until the
Loki activation contract is ready, namespace default-deny is live, exact
API-server egress is modeled, and the Phase 6 capacity admission passes.
