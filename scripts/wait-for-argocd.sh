#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/.." && pwd -P)
# shellcheck source=bootstrap/argocd/runtime-lib.sh
# Resolved from the validated repository root.
# shellcheck disable=SC1091
source "${repo_root}/bootstrap/argocd/runtime-lib.sh"

phase5_require_command helm
phase5_require_command kubectl
phase5_require_command python3
phase5_require_command realpath
phase5_assert_cluster_runtime "${repo_root}"

timeout=${ARGOCD_WAIT_TIMEOUT:-10m}
phase5_assert_timeout "${timeout}"
case "${timeout}" in
  *s) timeout_seconds=${timeout%s} ;;
  *m) timeout_seconds=$((10#${timeout%m} * 60)) ;;
esac

kubectl_base=(
  kubectl
  --kubeconfig "${KUBECONFIG}"
  --context "${PHASE5_KUBE_CONTEXT}"
  --request-timeout=30s
)
helm_base=(
  helm
  --kubeconfig "${KUBECONFIG}"
  --kube-context "${PHASE5_KUBE_CONTEXT}"
)

release_json=$("${helm_base[@]}" list --namespace argocd --filter '^argocd$' --output json)
python3 -c '
import json, sys
releases = json.load(sys.stdin)
if len(releases) != 1:
    raise SystemExit("exactly one argocd Helm release is required")
release = releases[0]
if release.get("chart") != "argo-cd-10.3.3" or release.get("app_version") != "v3.5.1":
    raise SystemExit("the live argocd release is not the pinned chart and application")
' <<<"${release_json}"

deadline=$((SECONDS + timeout_seconds))
while true; do
  workloads_json=$("${kubectl_base[@]}" -n argocd get deployment,statefulset -o json)
  if python3 -c '
import json, sys
expected = {
    "argocd-application-controller": 1,
    "argocd-applicationset-controller": 2,
    "argocd-redis": 1,
    "argocd-repo-server": 2,
    "argocd-server": 2,
}
items = json.load(sys.stdin).get("items", [])
found = {item.get("metadata", {}).get("name"): item for item in items}
if set(found) != set(expected):
    raise SystemExit(1)
for name, replicas in expected.items():
    item = found[name]
    spec_replicas = item.get("spec", {}).get("replicas", 1)
    status = item.get("status", {})
    if spec_replicas != replicas or status.get("observedGeneration") != item.get("metadata", {}).get("generation"):
        raise SystemExit(1)
    if status.get("readyReplicas", 0) != replicas or status.get("updatedReplicas", 0) != replicas:
        raise SystemExit(1)
' <<<"${workloads_json}" 2>/dev/null; then
    break
  fi
  (( SECONDS < deadline )) || phase5_fail 'Argo CD workloads did not converge before the timeout.'
  sleep 5
done

pods_json=$("${kubectl_base[@]}" -n argocd get pods -o json)
python3 -c '
import json, sys
pods = json.load(sys.stdin).get("items", [])
if not pods:
    raise SystemExit("the argocd namespace contains no pods")
for pod in pods:
    phase = pod.get("status", {}).get("phase")
    if phase == "Succeeded":
        continue
    statuses = pod.get("status", {}).get("containerStatuses", [])
    if phase != "Running" or not statuses or not all(item.get("ready") for item in statuses):
        raise SystemExit("an Argo CD pod is not Running and Ready")
' <<<"${pods_json}"

for crd in applications.argoproj.io applicationsets.argoproj.io appprojects.argoproj.io; do
  "${kubectl_base[@]}" wait --for=condition=Established "customresourcedefinition/${crd}" --timeout=60s >/dev/null
done

services_json=$("${kubectl_base[@]}" -n argocd get services -o json)
python3 -c '
import json, sys
services = json.load(sys.stdin).get("items", [])
if not services:
    raise SystemExit("the argocd namespace contains no Services")
names = {item.get("metadata", {}).get("name") for item in services}
if "argocd-server" not in names:
    raise SystemExit("the argocd-server Service is absent")
for item in services:
    spec = item.get("spec", {})
    if spec.get("type", "ClusterIP") != "ClusterIP":
        raise SystemExit("an Argo CD Service is publicly addressable")
    if spec.get("externalIPs") or spec.get("loadBalancerIP"):
        raise SystemExit("an Argo CD Service has an external address")
' <<<"${services_json}"

ingress_count=$("${kubectl_base[@]}" -n argocd get ingress -o json | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))')
[[ "${ingress_count}" == '0' ]] || phase5_fail 'Argo CD must not have ingress during day-zero bootstrap.'

config_json=$("${kubectl_base[@]}" -n argocd get configmap argocd-cm -o json)
params_json=$("${kubectl_base[@]}" -n argocd get configmap argocd-cmd-params-cm -o json)
rbac_json=$("${kubectl_base[@]}" -n argocd get configmap argocd-rbac-cm -o json)
python3 -c '
import json, sys
cm, params, rbac = (json.loads(value) for value in sys.argv[1:])
data = cm.get("data", {})
if data.get("users.anonymous.enabled") != "false":
    raise SystemExit("anonymous Argo CD access is not explicitly disabled")
if data.get("admin.enabled") != "true":
    raise SystemExit("the protected temporary administrator is not enabled")
if data.get("accounts.platform-admin") != "login" or data.get("accounts.reviewer") != "login":
    raise SystemExit("the required scoped Argo CD accounts are not configured")
health_lua = data.get("resource.customizations.health.argoproj.io_Application", "")
for required in ("obj.status.health.status", "obj.status.health.message", "return health"):
    if required not in health_lua:
        raise SystemExit("Application health does not deterministically mirror child health")
if params.get("data", {}).get("server.insecure") != "true":
    raise SystemExit("Argo CD internal HTTP is not enabled for Traefik TLS termination")
rbac_data = rbac.get("data", {})
if rbac_data.get("policy.default") != "role:authenticated":
    raise SystemExit("Argo CD does not use the explicit no-permission default role")
policy = rbac_data.get("policy.csv", "")
for required in (
    "platform-admin, role:admin",
    "reviewer, role:reviewer",
    "role:reviewer, applications, get, platform/*, allow",
    "role:reviewer, applications, sync, platform/*, deny",
):
    if required not in policy:
        raise SystemExit("required Argo CD RBAC binding is absent")
' "${config_json}" "${params_json}" "${rbac_json}"

project_json=$("${kubectl_base[@]}" -n argocd get appproject platform-bootstrap -o json)
python3 -c '
import json, sys
project = json.load(sys.stdin)
spec = project.get("spec", {})
if spec.get("sourceRepos") != ["https://github.com/kaycee1771/verda-platform-takehome.git"]:
    raise SystemExit("the bootstrap AppProject source allowlist changed")
if spec.get("destinations") != [{"namespace": "argocd", "server": "https://kubernetes.default.svc"}]:
    raise SystemExit("the bootstrap AppProject destination allowlist changed")
if spec.get("clusterResourceWhitelist"):
    raise SystemExit("the bootstrap AppProject permits cluster-scoped resources")
' <<<"${project_json}"

"${kubectl_base[@]}" -n argocd get endpointslice \
  -l kubernetes.io/service-name=argocd-server -o json | python3 -c '
import json, sys
slices = json.load(sys.stdin).get("items", [])
ready = sum(1 for item in slices for endpoint in item.get("endpoints", []) if endpoint.get("conditions", {}).get("ready"))
if ready != 2:
    raise SystemExit("argocd-server does not have exactly two ready endpoints")
'

printf '[PASS] Argo CD chart=10.3.3 workloads=ready tls=enabled anonymous=disabled exposure=ClusterIP-only.\n'
