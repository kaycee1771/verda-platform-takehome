#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

target="${1:-}"
mode="${2:-}"
case "$target" in
  verda-mgmt-server-01|verda-mgmt-server-02|verda-mgmt-server-03) ;;
  *) printf '%s\n' '[FAIL] invalid Phase 6 prepare target' >&2; exit 64 ;;
esac
if [[ -n "$mode" && "$mode" != '--post-quiesce' && "$mode" != '--post-recovery' ]]; then
  printf '%s\n' '[FAIL] invalid Phase 6 prepare mode' >&2
  exit 64
fi

kubectl_bin=/var/lib/rancher/rke2/bin/kubectl
kubeconfig=/etc/rancher/rke2/rke2.yaml
kubectl=("$kubectl_bin" --kubeconfig "$kubeconfig")

assert_survivors() {
  local ready
  ready="$("${kubectl[@]}" get nodes -o json | jq --arg target "$target" \
    '[.items[] | select(.metadata.name != $target) | select(any(.status.conditions[]; .type == "Ready" and .status == "True"))] | length')"
  [[ "$ready" == 2 ]] || { printf '%s\n' '[FAIL] two-survivor Ready gate failed' >&2; exit 1; }

  local healthy
  healthy="$(/usr/local/libexec/verda-phase4/etcdctl-local \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt \
    --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt \
    --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key \
    endpoint health --cluster --write-out=json | jq '[.[] | select(.health == true)] | length')"
  [[ "$healthy" -ge 2 ]] || { printf '%s\n' '[FAIL] two-survivor etcd quorum gate failed' >&2; exit 1; }
}

if [[ "$mode" == '--post-quiesce' ]]; then
  assert_survivors
  printf '%s\n' '[PASS] post-quiesce two-survivor boundary verified'
  exit 0
fi

if [[ "$mode" == '--post-recovery' ]]; then
  "${kubectl[@]}" -n longhorn-system patch nodes.longhorn.io "$target" --type=merge \
    -p '{"spec":{"allowScheduling":true,"evictionRequested":false}}' >/dev/null
  deadline=$((SECONDS + 900))
  while (( SECONDS < deadline )); do
    target_ready="$("${kubectl[@]}" get node "$target" -o json | jq \
      '[.status.conditions[] | select(.type == "Ready" and .status == "True")] | length')"
    longhorn_ready="$("${kubectl[@]}" -n longhorn-system get nodes.longhorn.io "$target" -o json | jq \
      '[.status.conditions[] | select((.type == "Ready" or .type == "Schedulable") and .status == "True")] | length')"
    volumes_json="$("${kubectl[@]}" -n longhorn-system get volumes.longhorn.io -o json)"
    volume_count="$(jq '.items | length' <<<"$volumes_json")"
    unhealthy="$(jq '[.items[] | select(.status.robustness != "healthy")] | length' <<<"$volumes_json")"
    if [[ "$target_ready" == 1 && "$longhorn_ready" == 2 && "$volume_count" -gt 0 && "$unhealthy" == 0 ]]; then
      assert_survivors
      printf '%s\n' '[PASS] replacement Ready and Longhorn scheduling/rebuild restored'
      exit 0
    fi
    sleep 10
  done
  printf '%s\n' '[FAIL] post-recovery readiness/Longhorn rebuild gate timed out' >&2
  exit 1
fi

assert_survivors
"${kubectl[@]}" cordon "$target" >/dev/null
"${kubectl[@]}" -n longhorn-system patch nodes.longhorn.io "$target" --type=merge \
  -p '{"spec":{"allowScheduling":false,"evictionRequested":true}}' >/dev/null

deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
  volumes_json="$("${kubectl[@]}" -n longhorn-system get volumes.longhorn.io -o json)"
  replicas_json="$("${kubectl[@]}" -n longhorn-system get replicas.longhorn.io -o json)"
  volume_count="$(jq '.items | length' <<<"$volumes_json")"
  unhealthy="$(jq '[.items[] | select(.status.robustness != "healthy")] | length' <<<"$volumes_json")"
  target_replicas="$(jq --arg target "$target" '[.items[] | select(.spec.nodeID == $target)] | length' <<<"$replicas_json")"
  if [[ "$volume_count" -gt 0 && "$unhealthy" == 0 && "$target_replicas" == 0 ]]; then
    break
  fi
  sleep 10
done
[[ "${volume_count:-0}" -gt 0 && "${unhealthy:-1}" == 0 && "${target_replicas:-1}" == 0 ]] || {
  printf '%s\n' '[FAIL] Longhorn evacuation/rebuild gate timed out' >&2
  exit 1
}

"${kubectl[@]}" drain "$target" --ignore-daemonsets --delete-emptydir-data --timeout=15m >/dev/null
assert_survivors
printf '%s\n' '[PASS] target cordoned, PDB-respecting drain completed, replicas evacuated, survivors healthy'
