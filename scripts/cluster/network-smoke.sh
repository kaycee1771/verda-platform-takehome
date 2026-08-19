#!/usr/bin/env bash
set -euo pipefail

kubeconfig=${KUBECONFIG:-/etc/rancher/rke2/rke2.yaml}
kubectl=${KUBECTL:-/var/lib/rancher/rke2/bin/kubectl}
manifest=${1:-/usr/local/share/verda-phase4/network-smoke.yaml}
namespace=phase4-network-test
keep_namespace=${PHASE4_KEEP_TEST_NAMESPACE:-false}

cleanup() {
  "${kubectl}" --kubeconfig "${kubeconfig}" delete namespace "${namespace}" \
    --ignore-not-found --wait=true --timeout=5m >/dev/null
}
if [[ "${keep_namespace}" != true ]]; then
  trap cleanup EXIT
fi
cleanup
"${kubectl}" --kubeconfig "${kubeconfig}" apply -f "${manifest}" >/dev/null
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" rollout status daemonset/echo --timeout=5m
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" rollout status daemonset/client --timeout=5m
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" wait pod/denied-client --for=condition=Ready --timeout=5m

mapfile -t servers < <("${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" get pod \
  -l app=phase4-echo -o jsonpath='{range .items[*]}{.status.podIP}{"|"}{.spec.nodeName}{"\n"}{end}')
mapfile -t clients < <("${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" get pod \
  -l app=phase4-client -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.spec.nodeName}{"\n"}{end}')

[[ "${#servers[@]}" -eq 3 && "${#clients[@]}" -eq 3 ]]
same_node=0
cross_node=0
for client_record in "${clients[@]}"; do
  IFS='|' read -r client client_node <<<"${client_record}"
  for server_record in "${servers[@]}"; do
    IFS='|' read -r server_ip server_node <<<"${server_record}"
    bytes=$("${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec "${client}" -- \
      sh -ec "curl -fsS --max-time 10 http://${server_ip}:8081/mtu.bin | wc -c")
    [[ "${bytes//[[:space:]]/}" == 1048576 ]]
    if [[ "${client_node}" == "${server_node}" ]]; then
      ((same_node += 1))
    else
      ((cross_node += 1))
    fi
  done
done
((same_node == 3 && cross_node == 6))

first_client=${clients[0]%%|*}
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec "${first_client}" -- \
  curl -fsS --max-time 10 http://echo/index.html | grep -qx phase4-ok
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec "${first_client}" -- \
  nslookup kubernetes.default.svc.cluster.local >/dev/null
"${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec "${first_client}" -- \
  curl -fsS --max-time 15 https://github.com/rancher/rke2 >/dev/null

if "${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec denied-client -- \
  curl -fsS --max-time 3 http://echo/index.html >/dev/null 2>&1; then
  echo '[FAIL] NetworkPolicy denied client reached the protected service.' >&2
  exit 1
fi

for wireguard_ip in 10.250.0.11 10.250.0.12 10.250.0.13; do
  curl -fsS --max-time 10 -H 'Host: phase4.internal' "http://${wireguard_ip}/index.html" | grep -qx phase4-ok
done

pod_mtu=$("${kubectl}" --kubeconfig "${kubeconfig}" -n "${namespace}" exec "${first_client}" -- \
  cat /sys/class/net/eth0/mtu)
[[ "${pod_mtu}" == 1370 ]]
echo '[PASS] same-node=3 cross-node=6 clusterip=true dns=true egress=true policy-deny=true traefik-nodes=3 mtu=1370 cleanup=armed'
