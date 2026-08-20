#!/usr/bin/env bash
set -euo pipefail

expected_node="${1:-}"
other_survivor_address="${2:-}"
if [[ ! "${expected_node}" =~ ^verda-mgmt-server-0[1-3]$ ]]; then
  echo '[FAIL] Exact stale management-node name is required.' >&2
  exit 64
fi
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
