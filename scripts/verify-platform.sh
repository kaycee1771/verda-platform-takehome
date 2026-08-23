#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$(uname -s)" == Linux ]] || { echo '[FAIL] Linux is required' >&2; exit 1; }
: "${KUBECONFIG:?KUBECONFIG must point to the protected read-only kubeconfig}"
command -v kubectl >/dev/null
command -v curl >/dev/null

fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }
pass() { printf '[PASS] %s\n' "$1"; }

kube=(kubectl)
if [[ -n "${PLATFORM_KUBE_SERVER:-}" || -n "${PLATFORM_KUBE_TLS_SERVER_NAME:-}" ]]; then
  [[ "${PLATFORM_KUBE_SERVER:-}" =~ ^https://[0-9]{1,3}(\.[0-9]{1,3}){3}:6443$ ]] ||
    fail 'PLATFORM_KUBE_SERVER must be https://IPv4:6443'
  [[ "${PLATFORM_KUBE_TLS_SERVER_NAME:-}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}\.sslip\.io$ ]] ||
    fail 'invalid PLATFORM_KUBE_TLS_SERVER_NAME'
  kube+=(--server "$PLATFORM_KUBE_SERVER" --tls-server-name "$PLATFORM_KUBE_TLS_SERVER_NAME")
fi

ready_nodes=$("${kube[@]}" get nodes -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -c '^True$')
[[ "$ready_nodes" -eq 3 ]] || fail "expected 3 Ready nodes, found $ready_nodes"
"${kube[@]}" get --raw='/readyz?verbose' | grep -q 'etcd.*ok' || fail 'API/etcd readiness'
pass 'Kubernetes nodes=3 etcd=ready'

workloads=(
  cattle-system/deployment/rancher
  harbor/deployment/harbor-core
  harbor/statefulset/harbor-trivy
  monitoring/statefulset/prometheus-monitoring-kube-prometheus-prometheus
  monitoring/deployment/monitoring-grafana
  loki/statefulset/loki
  logging/daemonset/alloy
  demo-dev/deployment/platform-demo
  demo-staging/deployment/platform-demo
  demo-prod/deployment/platform-demo
)
for workload in "${workloads[@]}"; do
  namespace=${workload%%/*}
  object=${workload#*/}
  "${kube[@]}" -n "$namespace" rollout status "$object" --timeout=5s >/dev/null ||
    fail "workload not ready: $workload"
done
pass 'Rancher Harbor Trivy Prometheus Grafana Loki Alloy applications=ready'

mapfile -t images < <(
  for namespace in demo-dev demo-staging demo-prod; do
    "${kube[@]}" -n "$namespace" get deployment platform-demo -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
  done
)
[[ "${#images[@]}" -eq 3 && "${images[0]}" == "${images[1]}" &&
   "${images[1]}" == "${images[2]}" && "${images[0]}" == *@sha256:* ]] ||
  fail 'environment image digests differ'
pass "environment digest=${images[0]##*@}"

not_ready=$("${kube[@]}" get certificates.cert-manager.io -A -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | grep -vc '^True$' || true)
[[ "$not_ready" -eq 0 ]] || fail "certificates not Ready: $not_ready"
pass 'certificates=ready'

for environment in dev staging prod; do
  url="https://platform-${environment}.95-133-252-214.nip.io/healthz"
  code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 15 "$url")
  [[ "$code" == 204 ]] || fail "${environment} endpoint returned ${code}"
done
pass 'public application endpoints=204'
pass 'platform verification complete (read-only)'
