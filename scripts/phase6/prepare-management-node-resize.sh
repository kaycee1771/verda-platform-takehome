#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

target="${1:-}"
mode="${2:-}"
authorization="${3:-}"
operation_id="${4:-}"
contract="${5:-}"
journal="${6:-}"
integrated_commit="${7:-}"
direction="${8:-}"
case "$target" in
  verda-mgmt-server-01|verda-mgmt-server-02|verda-mgmt-server-03) ;;
  *) printf '%s\n' '[FAIL] invalid Phase 6 prepare target' >&2; exit 64 ;;
esac
if [[ "$mode" != '--prepare' && "$mode" != '--post-quiesce' && "$mode" != '--post-recovery' ]]; then
  printf '%s\n' '[FAIL] invalid Phase 6 prepare mode' >&2
  exit 64
fi
authorization_mode=prepare
if [[ "$mode" == '--post-recovery' ]]; then authorization_mode=recover; fi
if [[ ! -f "$authorization" || ! -f "$contract" || ! -f "$journal" ||
      ! "$operation_id" =~ ^[0-9a-f]{64}$ || ! "$integrated_commit" =~ ^[0-9a-f]{40}$ ||
      ( "$direction" != resize && "$direction" != rollback ) ]]; then
  printf '%s\n' '[FAIL] protected Phase 6 operation authorization is absent' >&2
  exit 64
fi
for protected in "$authorization" "$contract" "$journal"; do
[[ "$(stat -c '%U:%a' "$protected")" == 'root:600' ]] || {
  printf '%s\n' '[FAIL] protected Phase 6 authorization ownership/mode differs' >&2
  exit 64
}
done
jq -e --arg operation "$operation_id" --arg node "${target##*-}" --arg mode "$authorization_mode" '
  .schema_version == 1 and .phase == 6 and .status == "CONTROLLER_OPERATION_AUTHORIZED" and
  .operation_id == $operation and .node == $node and .mode == $mode and
  .raw_values_recorded == false
' "$authorization" >/dev/null || {
  printf '%s\n' '[FAIL] protected Phase 6 operation authorization differs' >&2
  exit 64
}
contract_sha256="$(sha256sum "$contract" | awk '{print $1}')"
journal_sha256="$(sha256sum "$journal" | awk '{print $1}')"
jq -e --arg commit "$integrated_commit" '
  .phase == 6 and .cluster == "management" and .activation.enabled == true and
  .activation.writes_allowed == true and .activation.integrated_commit == $commit and
  .terraform.target_resource_expiry_utc == "2026-08-27T21:00:00Z"
' "$contract" >/dev/null || { printf '%s\n' '[FAIL] active Phase 6 contract differs' >&2; exit 64; }
expected_state=PREPARED
if [[ "$authorization_mode" == recover ]]; then expected_state=APPLIED; fi
jq -e --arg operation "$operation_id" --arg node "${target##*-}" --arg direction "$direction" \
  --arg commit "$integrated_commit" --arg state "$expected_state" '
  .phase == 6 and .integrated_commit == $commit and .operation_id == $operation and
  .node == $node and .direction == $direction and .state == $state
' "$journal" >/dev/null || { printf '%s\n' '[FAIL] Phase 6 journal state differs' >&2; exit 64; }
jq -e --arg contract "$contract_sha256" --arg journal "$journal_sha256" --arg commit "$integrated_commit" \
  --arg direction "$direction" '
  .contract_sha256 == $contract and .journal_sha256 == $journal and
  .integrated_commit == $commit and .direction == $direction
' "$authorization" >/dev/null || { printf '%s\n' '[FAIL] authorization hash binding differs' >&2; exit 64; }
expires_at="$(jq -r '.expires_at' "$authorization")"
expires_epoch="$(date -u -d "$expires_at" +%s 2>/dev/null || printf 0)"
now_epoch="$(date -u +%s)"
(( expires_epoch > now_epoch && expires_epoch - now_epoch <= 600 )) || {
  printf '%s\n' '[FAIL] protected Phase 6 authorization is expired' >&2
  exit 64
}

kubectl_bin=/var/lib/rancher/rke2/bin/kubectl
kubeconfig=/etc/rancher/rke2/rke2.yaml
kubectl=("$kubectl_bin" --kubeconfig "$kubeconfig")

assert_survivors() {
  local ready
  ready="$("${kubectl[@]}" get nodes -o json | jq --arg target "$target" \
    '[.items[] | select(.metadata.name != $target) | select(any(.status.conditions[]; .type == "Ready" and .status == "True"))] | length')"
  [[ "$ready" == 2 ]] || { printf '%s\n' '[FAIL] two-survivor Ready gate failed' >&2; exit 1; }

  local healthy
  local survivor_endpoints
  case "$target" in
    verda-mgmt-server-01) survivor_endpoints='https://10.250.0.12:2379,https://10.250.0.13:2379' ;;
    verda-mgmt-server-02) survivor_endpoints='https://10.250.0.11:2379,https://10.250.0.13:2379' ;;
    verda-mgmt-server-03) survivor_endpoints='https://10.250.0.11:2379,https://10.250.0.12:2379' ;;
  esac
  healthy="$(/usr/local/libexec/verda-phase4/etcdctl-local \
    --endpoints="$survivor_endpoints" \
    --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt \
    --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt \
    --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key \
    endpoint health --write-out=json | jq '[.[] | select(.health == true)] | length')"
  [[ "$healthy" == 2 ]] || { printf '%s\n' '[FAIL] two-survivor etcd quorum gate failed' >&2; exit 1; }
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
