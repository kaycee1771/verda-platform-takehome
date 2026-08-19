#!/usr/bin/env bash
set -euo pipefail

kubectl=${KUBECTL:-/var/lib/rancher/rke2/bin/kubectl}
kubeconfig=${KUBECONFIG_PATH:-/etc/rancher/rke2/rke2.yaml}
mode=${1:-}

namespace_list=$("${kubectl}" --kubeconfig "${kubeconfig}" get namespace -o name)
case "${mode}" in
  cilium)
    mapfile -t leftovers < <(
      grep -E '^namespace/cilium-test(-|$)' <<<"${namespace_list}" || true
    )
    if ((${#leftovers[@]} > 0)); then
      "${kubectl}" --kubeconfig "${kubeconfig}" delete "${leftovers[@]}" \
        --wait=true --timeout=5m >/dev/null
    fi
    post_namespace_list=$("${kubectl}" --kubeconfig "${kubeconfig}" get namespace -o name)
    if grep -Eq '^namespace/cilium-test(-|$)' <<<"${post_namespace_list}"; then
      echo '[FAIL] Cilium connectivity-test namespace cleanup did not converge.' >&2
      exit 1
    fi
    ;;
  network-smoke)
    "${kubectl}" --kubeconfig "${kubeconfig}" delete namespace phase4-network-test \
      --ignore-not-found --wait=true --timeout=5m >/dev/null
    post_namespace_list=$("${kubectl}" --kubeconfig "${kubeconfig}" get namespace -o name)
    if grep -Fxq 'namespace/phase4-network-test' <<<"${post_namespace_list}"; then
      echo '[FAIL] Phase 4 network-test namespace cleanup did not converge.' >&2
      exit 1
    fi
    ;;
  *)
    echo '[FAIL] Namespace cleanup mode is outside the Phase 4 allowlist.' >&2
    exit 64
    ;;
esac
