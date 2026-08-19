#!/usr/bin/env bash
set -euo pipefail

kubeconfig=${KUBECONFIG:-/etc/rancher/rke2/rke2.yaml}
kubectl=${KUBECTL:-/var/lib/rancher/rke2/bin/kubectl}
cilium=${CILIUM:-/usr/local/bin/cilium}
etcdctl=/usr/local/libexec/verda-phase4/etcdctl-local
hubble_metrics_gate=/usr/local/libexec/verda-phase4/hubble-metrics-gate
namespace_cleanup_helper=${PHASE4_NAMESPACE_CLEANUP_HELPER:-/usr/local/libexec/verda-phase4/cleanup-test-namespaces}

nodes_json=$("${kubectl}" --kubeconfig "${kubeconfig}" get nodes -o json)
python3 -c '
import json, sys
nodes=json.load(sys.stdin)["items"]
assert len(nodes)==3, f"expected 3 nodes, found {len(nodes)}"
for node in nodes:
  conditions={c["type"]:c["status"] for c in node["status"]["conditions"]}
  name=node["metadata"]["name"]
  assert conditions.get("Ready")=="True", "{} is not Ready".format(name)
  assert not node["spec"].get("unschedulable", False), "{} is unschedulable".format(name)
' <<<"${nodes_json}"

"${kubectl}" --kubeconfig "${kubeconfig}" get --raw='/readyz?verbose' | grep -q 'readyz check passed'
system_pods_deadline=$((SECONDS + 600))
while true; do
  system_pods_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get pods -o json)
  if python3 -c '
import json, sys
pods=json.load(sys.stdin)["items"]
assert pods, "kube-system has no pods"
unready=[]
for pod in pods:
  name=pod["metadata"]["name"]
  phase=pod.get("status", {}).get("phase", "Unknown")
  if phase == "Succeeded":
    continue
  statuses=pod.get("status", {}).get("containerStatuses", [])
  if phase != "Running" or not statuses or not all(item.get("ready") for item in statuses):
    unready.append("{}={}".format(name, phase))
assert not unready, "unready system pods: {}".format(", ".join(unready))
' <<<"${system_pods_json}" 2>/dev/null; then
    break
  fi
  if (( SECONDS >= system_pods_deadline )); then
    echo '[FAIL] kube-system pods did not converge within ten minutes.' >&2
    python3 -c '
import json, sys
for pod in json.load(sys.stdin)["items"]:
  name=pod["metadata"]["name"]
  phase=pod.get("status", {}).get("phase", "Unknown")
  statuses=pod.get("status", {}).get("containerStatuses", [])
  if phase != "Succeeded" and (phase != "Running" or not statuses or not all(item.get("ready") for item in statuses)):
    print("{}={}".format(name, phase), file=sys.stderr)
' <<<"${system_pods_json}"
    exit 1
  fi
  sleep 5
done
if "${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get pod --no-headers | \
  grep -Eq 'CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerError'; then
  echo '[FAIL] A kube-system pod is in a terminal or crash-loop state.' >&2
  exit 1
fi

etcd_args=(
  --endpoints=https://127.0.0.1:2379
  --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt
  --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt
  --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key
)
ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" endpoint health --cluster
ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" endpoint status --cluster --write-out=table
status_json=$(ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" endpoint status --cluster --write-out=json)
python3 -c '
import json, sys
entries=json.load(sys.stdin)
assert len(entries)==3, "expected status from three etcd endpoints"
statuses=[entry["Status"] for entry in entries]
member_ids={status["header"]["member_id"] for status in statuses}
leaders={status["leader"] for status in statuses}
assert len(member_ids)==3, "etcd member IDs are not unique"
assert len(leaders)==1 and 0 not in leaders, "etcd does not have one agreed non-zero leader"
leader=next(iter(leaders))
assert leader in member_ids, "the elected etcd leader is not an active member"
assert sum(status["header"]["member_id"]==leader for status in statuses)==1, "expected exactly one leader member"
for status in statuses:
  assert status["dbSize"] > 0, "etcd backend size is not positive"
  assert 0 < status["dbSizeInUse"] <= status["dbSize"], "etcd in-use backend size is invalid"
  assert status["raftTerm"] > 0, "etcd raft term is invalid"
  assert status["raftIndex"] > 0, "etcd raft index is invalid"
  assert 0 < status["raftAppliedIndex"] <= status["raftIndex"], "etcd raft apply state is invalid"
  assert status["header"]["revision"] > 0, "etcd revision is invalid"
print("[PASS] etcd-endpoints=3 leader-count=1 db-size=sane raft-applied=sane")
' <<<"${status_json}"
members=$(ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" member list --write-out=json)
python3 -c 'import json,sys; assert len(json.load(sys.stdin)["members"]) == 3' <<<"${members}"
alarms=$(ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" alarm list)
[[ -z "${alarms}" ]]

etcd_metrics=$(curl --fail --silent --show-error http://127.0.0.1:2381/metrics)
python3 -c '
import math, re, sys
metrics=sys.stdin.read().splitlines()
limits={
  "backend_commit_duration_seconds": 0.032,
  "wal_fsync_duration_seconds": 0.016,
}
for name, limit in limits.items():
  prefix="etcd_disk_{}_bucket".format(name)
  rows=[]
  for line in metrics:
    if not line.startswith(prefix + "{"):
      continue
    match=re.search(r"le=\"([^\"]+)\"} ([0-9.eE+-]+)$", line)
    assert match, "malformed etcd disk histogram"
    upper=math.inf if match.group(1)=="+Inf" else float(match.group(1))
    rows.append((upper, float(match.group(2))))
  rows.sort()
  assert rows and math.isinf(rows[-1][0]), "etcd disk histogram is incomplete"
  total=rows[-1][1]
  assert total > 0, "etcd disk histogram has no observations"
  target=total * 0.99
  p99=next(upper for upper, count in rows if count >= target)
  assert p99 <= limit, "etcd {} cumulative p99 bucket exceeds {}s".format(name, limit)
  print("[PASS] etcd-{} observations=true p99-bucket-seconds<={}".format(name, p99))
' <<<"${etcd_metrics}"

/usr/local/bin/rke2 secrets-encrypt status | grep -q 'Encryption Status: Enabled'
audit_log=/var/lib/rancher/rke2/server/logs/audit.log
test -s "${audit_log}"
"${kubectl}" --kubeconfig "${kubeconfig}" get --raw='/version' >/dev/null
audit_deadline=$((SECONDS + 15))
while ! python3 - "${audit_log}" <<'PY'
import json, os, sys
path=sys.argv[1]
with open(path, "rb") as stream:
    stream.seek(max(0, os.fstat(stream.fileno()).st_size - 1048576))
    lines=stream.read().decode("utf-8", errors="replace").splitlines()
for line in reversed(lines):
    try:
        event=json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("requestURI")=="/version" and event.get("stage")=="ResponseComplete":
        raise SystemExit(0)
raise SystemExit(1)
PY
do
  if (( SECONDS >= audit_deadline )); then
    echo '[FAIL] The known API readiness request was not observed in the audit log.' >&2
    exit 1
  fi
  sleep 1
done
/usr/local/bin/rke2 certificate check --output table
"${cilium}" status --kubeconfig "${kubeconfig}" --wait --wait-duration 10m
wait_for_metric_prefix() {
  local path="$1"
  local prefix="$2"
  local label="$3"
  local deadline=$((SECONDS + 120))
  local metrics=''
  while true; do
    metrics="$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get --raw "${path}" 2>/dev/null || true)"
    if grep -q "^${prefix}" <<<"${metrics}"; then
      echo "[PASS] ${label}=reachable metric-prefix=true"
      return 0
    fi
    if (( SECONDS >= deadline )); then
      echo "[FAIL] ${label} did not become reachable through the Kubernetes service proxy." >&2
      return 1
    fi
    sleep 3
  done
}
wait_for_metric_prefix \
  '/api/v1/namespaces/kube-system/services/http:hubble-metrics:9965/proxy/metrics' \
  'hubble_' 'hubble-agent-metrics'
wait_for_metric_prefix \
  '/api/v1/namespaces/kube-system/services/http:hubble-relay-metrics:9966/proxy/metrics' \
  'hubble_relay_' 'hubble-relay-metrics'
assert_cilium_runtime_boundary() {
  local cilium_pods_json kube_proxy_pods_json monitor_medium=0 kpr_false=0
  local pod runtime_json status_json
  cilium_pods_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get pods -l k8s-app=cilium -o json)
  mapfile -t cilium_pods < <(python3 -c '
import json, sys
pods=json.load(sys.stdin)["items"]
assert len(pods)==3, "expected exactly three Cilium agents"
for pod in sorted(pods, key=lambda item: item["metadata"]["name"]):
  print(pod["metadata"]["name"])
' <<<"${cilium_pods_json}")
  [[ ${#cilium_pods[@]} -eq 3 ]]
  for pod in "${cilium_pods[@]}"; do
    runtime_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
      exec "${pod}" -c cilium-agent -- \
      cat /var/run/cilium/state/agent-runtime-config.json)
    if python3 -c '
import json, sys
config=json.load(sys.stdin)
assert config.get("MonitorAggregation")=="medium"
' <<<"${runtime_json}"; then
      monitor_medium=$((monitor_medium + 1))
    else
      echo '[FAIL] A Cilium agent is not using monitor aggregation medium.' >&2
      return 1
    fi
    status_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
      exec "${pod}" -c cilium-agent -- cilium status -o json)
    if python3 -c '
import json, sys
status=json.load(sys.stdin)
# The Cilium StatusResponse model names this KubeProxyReplacement in Go and
# serializes it as kube-proxy-replacement in the pinned v1.19.6 agent JSON.
replacement=status.get("kube-proxy-replacement") or status.get("KubeProxyReplacement") or {}
assert replacement.get("mode")=="False"
' <<<"${status_json}"; then
      kpr_false=$((kpr_false + 1))
    else
      echo '[FAIL] A Cilium agent has enabled kube-proxy replacement.' >&2
      return 1
    fi
  done
  kube_proxy_pods_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get pods -l component=kube-proxy -o json)
  kube_proxy_ready=$(python3 -c '
import json, sys
pods=json.load(sys.stdin)["items"]
assert len(pods)==3, "expected exactly three kube-proxy pods"
ready=0
for pod in pods:
  conditions={item["type"]:item["status"] for item in pod.get("status",{}).get("conditions",[])}
  statuses=pod.get("status",{}).get("containerStatuses",[])
  if pod.get("status",{}).get("phase")=="Running" and conditions.get("Ready")=="True" and statuses and all(item.get("ready") for item in statuses):
    ready += 1
assert ready==3, "expected all three kube-proxy pods Ready"
print(ready)
' <<<"${kube_proxy_pods_json}")
  [[ ${monitor_medium} -eq 3 && ${kpr_false} -eq 3 && ${kube_proxy_ready} -eq 3 ]]
  echo '[PASS] cilium-agents=3 monitor-aggregation-medium=3 kpr-false=3 kube-proxy-ready=3/3'
}
assert_hubble_relay_peers() {
  local relay_pods_json pod relay_metrics relay_summary verified_replicas=0
  relay_pods_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get pods -l k8s-app=hubble-relay -o json)
  mapfile -t relay_pods < <(python3 -c '
import json, sys
pods=json.load(sys.stdin)["items"]
assert len(pods)==2, "expected exactly two Hubble Relay replicas"
for pod in sorted(pods, key=lambda item: item["metadata"]["name"]):
  print(pod["metadata"]["name"])
' <<<"${relay_pods_json}")
  [[ ${#relay_pods[@]} -eq 2 ]]
  for pod in "${relay_pods[@]}"; do
    relay_metrics=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get --raw \
      "/api/v1/namespaces/kube-system/pods/http:${pod}:9966/proxy/metrics")
    relay_summary=$("${hubble_metrics_gate}" relay-peers <<<"${relay_metrics}")
    [[ "${relay_summary}" == 'healthy=3 unavailable=0' ]]
    verified_replicas=$((verified_replicas + 1))
  done
  [[ ${verified_replicas} -eq 2 ]]
  echo '[PASS] hubble-relay-replicas=2 healthy-peers-per-replica=3 unavailable-peers=0'
}
assert_cilium_live_conformance() {
  local daemonset_json config_map_json cilium_pods_json pod_names pod
  local effective_capacity verified_agents=0
  local -a conformance_pods=()

  daemonset_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get daemonset cilium -o json)
  python3 -c '
import json, sys
daemonset=json.load(sys.stdin)
metadata=daemonset.get("metadata", {})
status=daemonset.get("status", {})
generation=metadata.get("generation")
assert type(generation) is int and generation > 0, "Cilium DaemonSet generation is invalid"
assert status.get("observedGeneration")==generation, "Cilium DaemonSet generation is not observed"
for field in (
  "desiredNumberScheduled",
  "currentNumberScheduled",
  "updatedNumberScheduled",
  "numberReady",
  "numberAvailable",
):
  assert type(status.get(field)) is int and status[field]==3, "Cilium DaemonSet rollout is incomplete"
unavailable=status.get("numberUnavailable", 0)
assert type(unavailable) is int and unavailable==0, "Cilium DaemonSet has unavailable agents"
strategy=daemonset.get("spec", {}).get("updateStrategy", {})
assert strategy.get("type")=="RollingUpdate", "Cilium DaemonSet strategy is not RollingUpdate"
max_unavailable=strategy.get("rollingUpdate", {}).get("maxUnavailable")
assert str(max_unavailable)=="1", "Cilium DaemonSet maxUnavailable is not one"
' <<<"${daemonset_json}"

  config_map_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get configmap cilium-config -o json)
  python3 -c '
import json, sys
config=json.load(sys.stdin)
data=config.get("data")
assert isinstance(data, dict), "Cilium ConfigMap data is absent"
assert data.get("hubble-event-buffer-capacity")=="8191", "Hubble event buffer capacity is not 8191"
' <<<"${config_map_json}"

  cilium_pods_json=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
    get pods -l k8s-app=cilium -o json)
  pod_names=$(python3 -c '
import json, sys
pods=json.load(sys.stdin).get("items")
assert isinstance(pods, list) and len(pods)==3, "expected exactly three Cilium agent pods"
for pod in sorted(pods, key=lambda item: item.get("metadata", {}).get("name", "")):
  metadata=pod.get("metadata", {})
  status=pod.get("status", {})
  name=metadata.get("name")
  assert isinstance(name, str) and name, "Cilium agent pod name is invalid"
  assert not metadata.get("deletionTimestamp"), "a Cilium agent pod is terminating"
  conditions={item.get("type"): item.get("status") for item in status.get("conditions", [])}
  containers={item.get("name"): item for item in status.get("containerStatuses", [])}
  assert status.get("phase")=="Running", "a Cilium agent pod is not Running"
  assert conditions.get("Ready")=="True", "a Cilium agent pod is not Ready"
  assert containers.get("cilium-agent", {}).get("ready") is True, "the Cilium agent container is not Ready"
  print(name)
' <<<"${cilium_pods_json}")
  mapfile -t conformance_pods <<<"${pod_names}"
  [[ ${#conformance_pods[@]} -eq 3 ]]
  for pod in "${conformance_pods[@]}"; do
    effective_capacity=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system \
      exec "${pod}" -c cilium-agent -- \
      cat /tmp/cilium/config-map/hubble-event-buffer-capacity)
    [[ "${effective_capacity}" == "8191" ]]
    verified_agents=$((verified_agents + 1))
  done
  [[ ${verified_agents} -eq 3 ]]
  cilium_pods=("${conformance_pods[@]}")
  echo '[PASS] cilium-live-conformance observed-generation=true desired=3 current=3 updated=3 ready=3 available=3 unavailable=0 strategy=RollingUpdate max-unavailable=1 hubble-event-buffer-capacity=8191 effective-agent-capacity=8191 effective-agents=3'
}
capture_hubble_lost_events() {
  local pod metrics
  for pod in "${cilium_pods[@]}"; do
    metrics=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get --raw \
      "/api/v1/namespaces/kube-system/pods/http:${pod}:9965/proxy/metrics")
    "${hubble_metrics_gate}" lost-snapshot --agent-key "${pod}" <<<"${metrics}"
  done
}
assert_zero_hubble_lost_event_delta() {
  local before="$1" after="$2" delta
  delta=$("${hubble_metrics_gate}" lost-delta \
    --before "${before}" --after "${after}" --expected-series 9)
  lost_event_positive_deltas=${delta}
  [[ ${lost_event_positive_deltas} -eq 0 ]]
  echo '[PASS] cilium-agents=3 hubble-lost-event-window=strict-canary hubble-lost-event-positive-deltas=0'
}
assert_cilium_runtime_boundary
assert_hubble_relay_peers
hubble_port_forward_pid=
stop_hubble_port_forward() {
  if [[ -n "${hubble_port_forward_pid}" ]]; then
    kill "${hubble_port_forward_pid}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "${hubble_port_forward_pid}" 2>/dev/null; then
        wait "${hubble_port_forward_pid}" 2>/dev/null || true
        hubble_port_forward_pid=
        return 0
      fi
      sleep 1
    done
    kill -KILL "${hubble_port_forward_pid}" 2>/dev/null || true
    for _ in $(seq 1 5); do
      if ! kill -0 "${hubble_port_forward_pid}" 2>/dev/null; then
        wait "${hubble_port_forward_pid}" 2>/dev/null || true
        hubble_port_forward_pid=
        return 0
      fi
      sleep 1
    done
    echo '[FAIL] The bounded local Hubble Relay port-forward did not terminate.' >&2
    return 1
  fi
}
cleanup_connectivity_best_effort() {
  stop_hubble_port_forward >/dev/null 2>&1 || true
  "${cilium}" connectivity test --kubeconfig "${kubeconfig}" \
    --hubble=false --test-namespace cilium-test --cleanup >/dev/null 2>&1 || true
  if [[ ${namespace_cleanup_helper} == /* && -x ${namespace_cleanup_helper} ]]; then
    "${namespace_cleanup_helper}" cilium >/dev/null 2>&1 || true
  fi
}
cleanup_connectivity_namespaces_required() {
  if [[ ${namespace_cleanup_helper} != /* || ! -x ${namespace_cleanup_helper} ]]; then
    echo '[FAIL] The required Phase 4 namespace cleanup helper is unavailable.' >&2
    return 1
  fi
  "${cilium}" connectivity test --kubeconfig "${kubeconfig}" \
    --hubble=false --test-namespace cilium-test --cleanup
  "${namespace_cleanup_helper}" cilium
  echo '[PASS] Cilium connectivity test namespaces removed.'
}
cleanup_connectivity_required() {
  stop_hubble_port_forward
  cleanup_connectivity_namespaces_required
}
trap cleanup_connectivity_best_effort EXIT

"${cilium}" connectivity test --kubeconfig "${kubeconfig}" \
  --hubble=false --test-namespace cilium-test --cleanup
assert_cilium_live_conformance
"${cilium}" connectivity test --kubeconfig "${kubeconfig}" \
  --test-namespace cilium-test \
  --hubble=false \
  --flow-validation disabled \
  --namespace-labels \
pod-security.kubernetes.io/enforce=privileged,pod-security.kubernetes.io/audit=privileged,pod-security.kubernetes.io/warn=privileged \
  --log-check-only-test-time \
  --test-concurrency 1 \
  --timeout 45m
cleanup_connectivity_namespaces_required
if timeout 1 bash -c '</dev/tcp/127.0.0.1/4245' 2>/dev/null; then
  echo '[FAIL] Local Hubble Relay port 4245 was already in use.' >&2
  exit 1
fi
"${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system port-forward \
  --address 127.0.0.1 service/hubble-relay 4245:80 >/dev/null 2>&1 &
hubble_port_forward_pid=$!
hubble_ready=false
for _ in $(seq 1 30); do
  if ! kill -0 "${hubble_port_forward_pid}" 2>/dev/null; then
    break
  fi
  if timeout 1 bash -c '</dev/tcp/127.0.0.1/4245' 2>/dev/null; then
    hubble_ready=true
    break
  fi
  sleep 1
done
if [[ "${hubble_ready}" != true ]]; then
  echo '[FAIL] The bounded local Hubble Relay port-forward did not become ready.' >&2
  exit 1
fi
if ! kill -0 "${hubble_port_forward_pid}" 2>/dev/null; then
  echo '[FAIL] The bounded local Hubble Relay port-forward exited after the readiness probe.' >&2
  exit 1
fi
lost_events_before_by_agent_source=$(capture_hubble_lost_events)
"${cilium}" connectivity test --kubeconfig "${kubeconfig}" \
  --test-namespace cilium-test \
  --test '^no-policies/pod-to-pod$' \
  --hubble=true \
  --hubble-server 127.0.0.1:4245 \
  --flow-validation strict \
  --namespace-labels \
pod-security.kubernetes.io/enforce=privileged,pod-security.kubernetes.io/audit=privileged,pod-security.kubernetes.io/warn=privileged \
  --log-check-only-test-time \
  --test-concurrency 1 \
  --timeout 15m
lost_events_after_by_agent_source=$(capture_hubble_lost_events)
assert_zero_hubble_lost_event_delta "${lost_events_before_by_agent_source}" "${lost_events_after_by_agent_source}"
assert_hubble_relay_peers
cleanup_connectivity_required
trap - EXIT

echo '[PASS] nodes=3 ready=3 schedulable=3 api=true system-pods=true etcd-members=3 leader=1 db=true disk=true alarms=0 encryption=true audit-request=true cilium=true hubble-metrics=true connectivity=true'
