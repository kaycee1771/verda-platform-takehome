#!/usr/bin/env bash
set -euo pipefail

expected_node="${1:-}"
other_survivor_address="${2:-}"
authorization="${3:-}"
operation_id="${4:-}"
contract="${5:-}"
journal="${6:-}"
integrated_commit="${7:-}"
direction="${8:-}"
if [[ ! "${expected_node}" =~ ^verda-mgmt-server-0[1-3]$ ]]; then
  echo '[FAIL] Exact stale management-node name is required.' >&2
  exit 64
fi
if [[ ! -f "$authorization" || ! -f "$contract" || ! -f "$journal" ||
      ! "$operation_id" =~ ^[0-9a-f]{64}$ || ! "$integrated_commit" =~ ^[0-9a-f]{40}$ ||
      ( "$direction" != resize && "$direction" != rollback ) ||
      "$(stat -c '%U:%a' "$authorization" 2>/dev/null || true)" != 'root:600' ||
      "$(stat -c '%U:%a' "$contract" 2>/dev/null || true)" != 'root:600' ||
      "$(stat -c '%U:%a' "$journal" 2>/dev/null || true)" != 'root:600' ]]; then
  echo '[FAIL] Protected Phase 6 recovery authorization is absent.' >&2
  exit 64
fi
jq -e --arg operation "$operation_id" --arg node "${expected_node##*-}" '
  .schema_version == 1 and .phase == 6 and .status == "CONTROLLER_OPERATION_AUTHORIZED" and
  .operation_id == $operation and .node == $node and .mode == "recover" and
  .raw_values_recorded == false
' "$authorization" >/dev/null || { echo '[FAIL] Recovery authorization differs.' >&2; exit 64; }
contract_sha256="$(sha256sum "$contract" | awk '{print $1}')"
journal_sha256="$(sha256sum "$journal" | awk '{print $1}')"
jq -e --arg commit "$integrated_commit" '
  .phase == 6 and .cluster == "management" and .activation.enabled == true and
  .activation.writes_allowed == true and .activation.integrated_commit == $commit and
  .terraform.target_resource_expiry_utc == "2026-08-27T21:00:00Z"
' "$contract" >/dev/null || { echo '[FAIL] Active Phase 6 contract differs.' >&2; exit 64; }
jq -e --arg operation "$operation_id" --arg node "${expected_node##*-}" --arg direction "$direction" \
  --arg commit "$integrated_commit" '
  .phase == 6 and .integrated_commit == $commit and .operation_id == $operation and
  .node == $node and .direction == $direction and .state == "APPLIED"
' "$journal" >/dev/null || { echo '[FAIL] Phase 6 journal state differs.' >&2; exit 64; }
jq -e --arg contract "$contract_sha256" --arg journal "$journal_sha256" --arg commit "$integrated_commit" \
  --arg direction "$direction" '
  .contract_sha256 == $contract and .journal_sha256 == $journal and
  .integrated_commit == $commit and .direction == $direction
' "$authorization" >/dev/null || { echo '[FAIL] Authorization hash binding differs.' >&2; exit 64; }
expires_epoch="$(date -u -d "$(jq -r '.expires_at' "$authorization")" +%s 2>/dev/null || printf 0)"
now_epoch="$(date -u +%s)"
(( expires_epoch > now_epoch && expires_epoch - now_epoch <= 600 )) || {
  echo '[FAIL] Recovery authorization is expired.' >&2
  exit 64
}
if [[ ! "${other_survivor_address}" =~ ^10\.250\.0\.1[123]$ ]]; then
  echo '[FAIL] Exact private address of the other survivor is required.' >&2
  exit 64
fi

etcdctl=(
  /usr/local/libexec/verda-phase4/etcdctl-local
  --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt
  --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt
  --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key
)

raw_members="$("${etcdctl[@]}" --endpoints=https://127.0.0.1:2379 member list)"
member_count="$(sed '/^[[:space:]]*$/d' <<<"${raw_members}" | wc -l)"
if [[ "${member_count}" -ne 3 ]]; then
  echo '[FAIL] Refusing stale-member removal outside the exact three-member starting state.' >&2
  exit 1
fi

mapfile -t matches < <(awk -F ', ' -v node="${expected_node}" '$3 == node {print $1}' <<<"${raw_members}")
if [[ "${#matches[@]}" -ne 1 || ! "${matches[0]}" =~ ^[0-9a-f]{16}$ ]]; then
  echo '[FAIL] Expected exactly one stale etcd member with the selected node name.' >&2
  exit 1
fi

# The replacement must not already be active under the stale Kubernetes identity.
ready="$('/var/lib/rancher/rke2/bin/kubectl' --kubeconfig /etc/rancher/rke2/rke2.yaml \
  get node "${expected_node}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
if [[ "${ready}" == 'True' ]]; then
  echo '[FAIL] Refusing to remove an etcd member whose Kubernetes node is Ready.' >&2
  exit 1
fi

"${etcdctl[@]}" --endpoints="https://127.0.0.1:2379,https://${other_survivor_address}:2379" endpoint health >/dev/null
"${etcdctl[@]}" --endpoints=https://127.0.0.1:2379 member remove "${matches[0]}" >/dev/null

remaining="$("${etcdctl[@]}" --endpoints=https://127.0.0.1:2379 member list | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "${remaining}" -ne 2 ]]; then
  echo '[FAIL] Etcd membership did not converge to the exact two-survivor floor.' >&2
  exit 1
fi
"${etcdctl[@]}" --endpoints="https://127.0.0.1:2379,https://${other_survivor_address}:2379" endpoint health >/dev/null

'/var/lib/rancher/rke2/bin/kubectl' --kubeconfig /etc/rancher/rke2/rke2.yaml \
  delete node "${expected_node}" --ignore-not-found=true --wait=true --timeout=60s >/dev/null

echo '[PASS] Exact stale member and stale Kubernetes node identity removed; two-member quorum remains healthy.'
