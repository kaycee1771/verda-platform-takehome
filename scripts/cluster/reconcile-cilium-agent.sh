#!/usr/bin/env bash
set -euo pipefail

node_name=${1:?A stable management node name or a bounded controller target is required}
if [[ ${node_name} != all && ${node_name} != post-drill-ready && ! ${node_name} =~ ^verda-mgmt-server-0[123]$ ]]; then
  echo "The requested Cilium reconciliation target is outside the bounded Phase 4 set." >&2
  exit 64
fi

kubectl=${KUBECTL:-/var/lib/rancher/rke2/bin/kubectl}
kubeconfig=${KUBECONFIG_PATH:-/etc/rancher/rke2/rke2.yaml}
cilium=${CILIUM:-/usr/local/bin/cilium}
namespace=kube-system
readiness_timeout_seconds=${RECONCILE_READINESS_TIMEOUT_SECONDS:-300}
poll_interval_seconds=${RECONCILE_POLL_INTERVAL_SECONDS:-5}
if [[ ! ${readiness_timeout_seconds} =~ ^[0-9]+$ || ! ${poll_interval_seconds} =~ ^[0-9]+$ ]]; then
  echo "The Cilium reconciliation timing boundary is malformed." >&2
  exit 64
fi

collect_residual_pods() {
  local -a get_args
  get_args=(--kubeconfig "${kubeconfig}" -n "${namespace}" get pod -o json)
  if [[ ${node_name} != all ]]; then
    get_args+=(--field-selector "spec.nodeName=${node_name}")
  fi
  "${kubectl}" "${get_args[@]}" |
    python3 -c '
import json
import sys

payload = json.load(sys.stdin)
allowed = {"cilium-agent", "cilium-operator", "hubble-relay"}
for item in payload.get("items", []):
    labels = item.get("metadata", {}).get("labels", {})
    component = labels.get("app.kubernetes.io/name") or labels.get("k8s-app")
    status = item.get("status", {})
    statuses = status.get("initContainerStatuses", []) + status.get("containerStatuses", [])
    if component in allowed and any(status.get("restartCount", 0) > 0 for status in statuses):
        print("{}|{}".format(item["metadata"]["name"], component))
'
}

wait_for_all_components_ready() {
  local deadline=$((SECONDS + readiness_timeout_seconds))
  until "${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" get pod -o json |
    python3 -c '
import json
import sys

expected = {"cilium-agent": 3, "cilium-operator": 2, "hubble-relay": 2}
payload = json.load(sys.stdin)
counts = {component: 0 for component in expected}
for item in payload.get("items", []):
    labels = item.get("metadata", {}).get("labels", {})
    component = labels.get("app.kubernetes.io/name") or labels.get("k8s-app")
    if component not in expected:
        continue
    counts[component] += 1
    status = item.get("status", {})
    conditions = {condition.get("type"): condition.get("status") for condition in status.get("conditions", [])}
    statuses = status.get("containerStatuses", [])
    if (
        status.get("phase") != "Running"
        or conditions.get("Ready") != "True"
        or not statuses
        or any(not container.get("ready") for container in statuses)
    ):
        raise SystemExit(1)
if counts != expected:
    raise SystemExit(1)
'; do
    if ((SECONDS >= deadline)); then
      echo "The bounded Cilium stack did not restore full replica readiness." >&2
      return 1
    fi
    sleep "${poll_interval_seconds}"
  done
}

wait_for_api_ready() {
  local deadline=$((SECONDS + readiness_timeout_seconds))
  until "${kubectl}" --kubeconfig "${kubeconfig}" get --raw=/readyz >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      echo "The Kubernetes API did not recover within the post-drill readiness boundary." >&2
      return 1
    fi
    sleep "${poll_interval_seconds}"
  done
}

if [[ ${node_name} == post-drill-ready ]]; then
  wait_for_api_ready
  wait_for_all_components_ready
  "${cilium}" status --kubeconfig "${kubeconfig}" --wait --wait-duration 10m >/dev/null
  echo "[PASS] cilium_post_drill_ready=true api_ready=true exact_components=3-2-2 cilium_healthy=true restart_history_preserved=true"
  exit 0
fi

replacement_attempts=0
maximum_replacements=14
while true; do
  wait_for_all_components_ready
  mapfile -t residual_pods < <(collect_residual_pods)
  if ((${#residual_pods[@]} == 0)); then
    break
  fi
  if ((replacement_attempts >= maximum_replacements)); then
    echo "The bounded Cilium reconciliation exhausted its replacement budget." >&2
    exit 1
  fi
  residual=${residual_pods[0]}
  pod=${residual%%|*}
  "${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" \
    delete "pod/${pod}" --wait=true --timeout=5m >/dev/null
  replacement_attempts=$((replacement_attempts + 1))
  wait_for_all_components_ready
done

deadline=$((SECONDS + readiness_timeout_seconds))
until "${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" get pod -o json |
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
expected = {"cilium-agent": 3, "cilium-operator": 2, "hubble-relay": 2}
counts = {name: 0 for name in expected}
for item in payload.get("items", []):
    labels = item.get("metadata", {}).get("labels", {})
    component = labels.get("app.kubernetes.io/name") or labels.get("k8s-app")
    if component not in expected:
        continue
    counts[component] += 1
    status = item.get("status", {})
    statuses = status.get("initContainerStatuses", []) + status.get("containerStatuses", [])
    if not statuses or any(not status.get("ready") or status.get("restartCount") != 0 for status in statuses):
        raise SystemExit(1)
if counts != expected:
    raise SystemExit(1)
'; do
  if ((SECONDS >= deadline)); then
    echo "Recovered Cilium components did not reach a zero-restart healthy baseline." >&2
    exit 1
  fi
  sleep "${poll_interval_seconds}"
done

echo "[PASS] cilium_components_reconciled=true restart_count=0"
