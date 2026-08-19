#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo '[FAIL] Root is required for the Phase 4 stability window.' >&2
  exit 1
fi

kubeconfig=/etc/rancher/rke2/rke2.yaml
kubectl=/var/lib/rancher/rke2/bin/kubectl
etcdctl=/usr/local/libexec/verda-phase4/etcdctl-local
work_dir=$(mktemp -d -t verda-phase4-stability.XXXXXX)
cleanup() { rm -rf -- "${work_dir}"; }
trap cleanup EXIT

capture_state() {
  "${kubectl}" --kubeconfig "${kubeconfig}" get nodes -o json >"${work_dir}/nodes.json"
  "${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get pods -o json >"${work_dir}/pods.json"
}

/usr/local/bin/cilium status --kubeconfig "${kubeconfig}" --wait --wait-duration 10m >/dev/null
capture_state
cp "${work_dir}/pods.json" "${work_dir}/baseline-pods.json"
for sample in $(seq 1 10); do
  capture_state
  python3 - "${work_dir}/nodes.json" "${work_dir}/baseline-pods.json" "${work_dir}/pods.json" <<'PY'
import json, sys
nodes=json.load(open(sys.argv[1], encoding="utf-8"))["items"]
assert len(nodes)==3, "stability window no longer has three nodes"
for node in nodes:
    conditions={item["type"]:item["status"] for item in node["status"]["conditions"]}
    assert conditions.get("Ready")=="True", "a node became NotReady during the stability window"

def running_state(path):
    result={}
    for pod in json.load(open(path, encoding="utf-8"))["items"]:
        phase=pod.get("status", {}).get("phase", "Unknown")
        if phase=="Succeeded":
            continue
        status=pod.get("status", {})
        statuses=status.get("containerStatuses", [])
        assert phase=="Running" and statuses and all(item.get("ready") for item in statuses), \
            "a kube-system workload became unhealthy during the stability window"
        for status_class, items in (
            ("init", status.get("initContainerStatuses", [])),
            ("app", statuses),
        ):
            for item in items:
                result[(pod["metadata"]["uid"], status_class, item["name"])]=item.get("restartCount", 0)
    return result

baseline=running_state(sys.argv[2])
current=running_state(sys.argv[3])
assert current==baseline, "a kube-system pod changed identity or restart count during the stability window"
PY
  "${kubectl}" --kubeconfig "${kubeconfig}" get --raw='/readyz' >/dev/null
  if (( sample < 10 )); then sleep 30; fi
done

/usr/local/bin/cilium status --kubeconfig "${kubeconfig}" --wait --wait-duration 10m >/dev/null
etcd_args=(
  --endpoints=https://127.0.0.1:2379
  --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt
  --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt
  --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key
)
ETCDCTL_API=3 "${etcdctl}" "${etcd_args[@]}" endpoint health --cluster >/dev/null
printf '%s\n' '{"schema_version":1,"status":"PASS","duration_seconds":270,"samples":10,"nodes_ready":3,"system_pod_identity_stable":true,"restart_counts_unchanged":true,"api_ready":true,"etcd_healthy":true,"cilium_healthy":true}'
