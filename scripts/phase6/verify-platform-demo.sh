#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

# Read-only Platform runtime acceptance. Runtime credentials and endpoints are
# consumed only from owner-only files outside Git. The verifier writes API
# responses to a private temporary directory and emits fixed aggregate facts.

fail() {
  printf '[FAIL] gate=%s\n' "$1" >&2
  exit 1
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail 'required-input'
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail 'dependency'
}

require_protected_file() {
  local path="$1"
  local mode owner
  [[ "$path" == /* && -f "$path" && ! -L "$path" ]] || fail 'protected-file'
  mode=$(stat -c '%a' -- "$path" 2>/dev/null) || fail 'protected-file'
  owner=$(stat -c '%u' -- "$path" 2>/dev/null) || fail 'protected-file'
  [[ "$mode" == '600' && "$owner" == "$(id -u)" ]] || fail 'protected-file'
  [[ $(stat -c '%s' -- "$path" 2>/dev/null) -le 65536 ]] || fail 'protected-file'
}

require_authorization_file() {
  local path="$1"
  local scheme="$2"
  if ! "$python_bin" -c '
import pathlib, re, sys
data = pathlib.Path(sys.argv[1]).read_bytes()
scheme = sys.argv[2].encode("ascii")
assert 24 <= len(data) <= 16384
assert b"\r" not in data and data.count(b"\n") <= 1
line = data.removesuffix(b"\n")
assert line.startswith(b"Authorization: " + scheme + b" ")
value = line.split(b" ", 2)[2]
assert re.fullmatch(rb"[A-Za-z0-9._~+/=:-]+", value)
' "$path" "$scheme" >/dev/null 2>&1; then
    fail 'authorization-file'
  fi
}

private_output() {
  local path="$1"
  : >"$path" || fail 'runtime-directory'
  chmod 600 "$path" || fail 'runtime-directory'
}

kube_json() {
  local output="$1"
  shift
  private_output "$output"
  "${kube[@]}" "$@" -o json >"$output" 2>/dev/null || fail 'kubernetes-read'
}

kube_raw() {
  local output="$1"
  local path="$2"
  private_output "$output"
  "${kube[@]}" get --raw "$path" >"$output" 2>/dev/null || fail 'kubernetes-read'
}

api_get() {
  local endpoint="$1"
  local authorization_file="$2"
  local path="$3"
  local output="$4"
  private_output "$output"
  "$curl_bin" --silent --show-error --fail --max-redirs 0 --max-time 30 \
    --proto '=https' --tlsv1.2 --header "@$authorization_file" \
    --output "$output" "${endpoint}${path}" 2>/dev/null || fail 'authenticated-api'
}

api_status() {
  local endpoint="$1"
  local authorization_file="$2"
  local path="$3"
  local output="$4"
  private_output "$output"
  "$curl_bin" --silent --show-error --max-redirs 0 --max-time 30 \
    --proto '=https' --tlsv1.2 --header "@$authorization_file" \
    --output "$output" --write-out '%{http_code}' "${endpoint}${path}" 2>/dev/null
}

cleanup() {
  if [[ -n "${runtime_dir:-}" && -d "$runtime_dir" && \
        "$(basename -- "$runtime_dir")" == verda-phase6-acceptance.* ]]; then
    rm -rf -- "$runtime_dir"
  fi
}

readonly argocd_root_app='platform-root'
readonly -a argocd_child_apps=(
  'platform-project'
  'cert-manager-controller'
  'argocd-certificate-staging'
  'longhorn-prerequisites'
  'longhorn-controller'
  'longhorn-resources'
  'argocd-certificate-production'
  'argocd-public-ingress'
  'platform-namespaces'
  'sealed-secrets-controller'
  'kyverno-controller'
  'rancher'
  'harbor-secrets'
  'harbor-postgresql'
  'harbor'
  'monitoring'
  'monitoring-resources'
  'loki'
  'alloy'
  'velero-controller'
  'velero-resources'
  'kyverno-policies'
  'sealed-secrets-monitoring'
  'kyverno-monitoring'
  'argocd-monitoring'
  'harbor-monitoring'
  'longhorn-monitoring'
  'rancher-monitoring'
  'traefik-monitoring'
  'demo-dev-foundation'
  'demo-staging-foundation'
  'demo-prod-foundation'
  'platform-demo-dev'
  'platform-demo-staging'
  'platform-demo-prod'
)
readonly -a environments=('dev' 'staging' 'prod')
readonly -a namespaces=('demo-dev' 'demo-staging' 'demo-prod')
readonly -a expected_replicas=(1 1 2)

for name in \
  PHASE6_KUBECONFIG \
  PHASE6_KUBE_CONTEXT \
  PHASE6_RANCHER_ENDPOINT_FILE \
  PHASE6_RANCHER_REVIEWER_TOKEN_FILE \
  PHASE6_HARBOR_ENDPOINT_FILE \
  PHASE6_HARBOR_REVIEWER_TOKEN_FILE \
  PHASE6_GRAFANA_ENDPOINT_FILE \
  PHASE6_GRAFANA_REVIEWER_TOKEN_FILE \
  PHASE6_APPLICATION_ENDPOINTS_FILE \
  PHASE6_CAPACITY_EVIDENCE_FILE; do
  require_value "$name"
done

kubectl_bin=${PHASE6_KUBECTL_BIN:-kubectl}
curl_bin=${PHASE6_CURL_BIN:-curl}
python_bin=${PHASE6_PYTHON_BIN:-python3}
for binary in "$kubectl_bin" "$curl_bin" "$python_bin" stat id mktemp chmod rm; do
  require_command "$binary"
done

for protected_file in \
  "$PHASE6_KUBECONFIG" \
  "$PHASE6_RANCHER_ENDPOINT_FILE" \
  "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" \
  "$PHASE6_HARBOR_ENDPOINT_FILE" \
  "$PHASE6_HARBOR_REVIEWER_TOKEN_FILE" \
  "$PHASE6_GRAFANA_ENDPOINT_FILE" \
  "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" \
  "$PHASE6_APPLICATION_ENDPOINTS_FILE" \
  "$PHASE6_CAPACITY_EVIDENCE_FILE"; do
  require_protected_file "$protected_file"
done
require_authorization_file "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" Bearer
require_authorization_file "$PHASE6_HARBOR_REVIEWER_TOKEN_FILE" Basic
require_authorization_file "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" Bearer

[[ "$PHASE6_KUBE_CONTEXT" =~ ^[A-Za-z0-9._@:/-]+$ ]] || fail 'kube-context'

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/verda-phase6-acceptance.XXXXXX") || \
  fail 'runtime-directory'
trap cleanup EXIT
chmod 700 "$runtime_dir" || fail 'runtime-directory'

endpoints_file="$runtime_dir/endpoints"
private_output "$endpoints_file"
if ! "$python_bin" -c '
import ipaddress, json, pathlib, re, sys

def one(path, service):
    rows = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and rows[0] == rows[0].strip()
    pattern = rf"https://{service}\.([0-9]{{1,3}}(?:-[0-9]{{1,3}}){{3}})\.sslip\.io"
    match = re.fullmatch(pattern, rows[0])
    assert match
    ipaddress.IPv4Address(match.group(1).replace("-", "."))
    return rows[0], match.group(1)

rancher, address = one(sys.argv[1], "rancher")
harbor, harbor_address = one(sys.argv[2], "harbor")
grafana, grafana_address = one(sys.argv[3], "grafana")
assert address == harbor_address == grafana_address
apps = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
assert set(apps) == {"dev", "staging", "prod"}
values = []
for environment in ("dev", "staging", "prod"):
    value = apps[environment]
    match = re.fullmatch(
        rf"https://demo-{environment}\.([0-9]{{1,3}}(?:-[0-9]{{1,3}}){{3}})\.sslip\.io",
        value,
    )
    assert match and match.group(1) == address
    values.append(value)
print(rancher, harbor, grafana, *values, sep="\n")
' "$PHASE6_RANCHER_ENDPOINT_FILE" "$PHASE6_HARBOR_ENDPOINT_FILE" \
  "$PHASE6_GRAFANA_ENDPOINT_FILE" "$PHASE6_APPLICATION_ENDPOINTS_FILE" \
  >"$endpoints_file" 2>/dev/null; then
  fail 'endpoint-contract'
fi
mapfile -t endpoints <"$endpoints_file"
[[ ${#endpoints[@]} -eq 6 ]] || fail 'endpoint-contract'
rancher_endpoint=${endpoints[0]}
harbor_endpoint=${endpoints[1]}
grafana_endpoint=${endpoints[2]}
application_endpoints=("${endpoints[@]:3:3}")
unset endpoints
printf '[PASS] protected-inputs=10 endpoints=validated authorization=files-only\n'

kube=(
  "$kubectl_bin"
  --kubeconfig "$PHASE6_KUBECONFIG"
  --context "$PHASE6_KUBE_CONTEXT"
  --request-timeout=20s
)
configured_context=$("${kube[@]}" config current-context 2>/dev/null) || fail 'kube-context'
selected_context=$(
  "${kube[@]}" config get-contexts "$PHASE6_KUBE_CONTEXT" -o name 2>/dev/null
) || fail 'kube-context'
[[ "$configured_context" == "$PHASE6_KUBE_CONTEXT" && \
   "$selected_context" == "$PHASE6_KUBE_CONTEXT" ]] || fail 'kube-context'

kubeconfig_view="$runtime_dir/kubeconfig-view.json"
nodes_json="$runtime_dir/nodes.json"
private_output "$kubeconfig_view"
"${kube[@]}" config view --minify -o json >"$kubeconfig_view" 2>/dev/null || \
  fail 'direct-kubeconfig'
kube_json "$nodes_json" get nodes
if ! "$python_bin" -c '
import json, sys, urllib.parse
config = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = json.load(open(sys.argv[2], encoding="utf-8")).get("items", [])
rancher = urllib.parse.urlparse(sys.argv[3])
clusters = config.get("clusters", [])
assert len(clusters) == 1
server = urllib.parse.urlparse(clusters[0].get("cluster", {}).get("server", ""))
assert server.scheme == "https" and server.hostname and server.hostname != rancher.hostname
assert len(nodes) == 3
for node in nodes:
    conditions = node.get("status", {}).get("conditions", [])
    assert any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
' "$kubeconfig_view" "$nodes_json" "$rancher_endpoint" >/dev/null 2>&1; then
  fail 'direct-kubeconfig'
fi
printf '[PASS] kube-context=exact management-nodes=3 direct-api=ready\n'

applications_json="$runtime_dir/argocd-applications.json"
kube_json "$applications_json" -n argocd get applications.argoproj.io
if ! application_count=$(
  "$python_bin" -c '
import json, sys
expected = sys.argv[1:]
assert len(expected) == len(set(expected))
items = json.load(open(sys.stdin.fileno(), encoding="utf-8")).get("items", [])
by_name = {item.get("metadata", {}).get("name"): item for item in items}
assert len(by_name) == len(items) and set(by_name) == set(expected)
for name in expected:
    item = by_name[name]
    status = item.get("status", {})
    assert status.get("health", {}).get("status") == "Healthy"
    assert status.get("sync", {}).get("status") == "Synced"
    destination = item.get("spec", {}).get("destination", {})
    assert destination.get("server") == "https://kubernetes.default.svc"
    assert not destination.get("name")
print(len(expected))
' "$argocd_root_app" "${argocd_child_apps[@]}" <"$applications_json" 2>/dev/null
); then
  fail 'argocd-applications'
fi
[[ "$application_count" == "$(( ${#argocd_child_apps[@]} + 1 ))" ]] || \
  fail 'argocd-applications'
printf '[PASS] argocd-applications=%s healthy=%s synced=%s destinations=local-only\n' \
  "$application_count" "$application_count" "$application_count"

namespace_json="$runtime_dir/namespaces.json"
kube_json "$namespace_json" get namespaces "${namespaces[@]}"
for index in "${!namespaces[@]}"; do
  environment=${environments[index]}
  namespace=${namespaces[index]}
  quota_json="$runtime_dir/${environment}-quota.json"
  limits_json="$runtime_dir/${environment}-limits.json"
  policies_json="$runtime_dir/${environment}-policies.json"
  service_account_json="$runtime_dir/${environment}-service-account.json"
  role_binding_json="$runtime_dir/${environment}-role-binding.json"
  kube_json "$quota_json" -n "$namespace" get resourcequota platform-budget
  kube_json "$limits_json" -n "$namespace" get limitrange workload-defaults
  kube_json "$policies_json" -n "$namespace" get networkpolicy default-deny allow-cluster-dns
  kube_json "$service_account_json" -n "$namespace" get serviceaccount platform-demo
  kube_json "$role_binding_json" -n "$namespace" get rolebinding verda-reviewers-view
  pull_secret_name=$(
    "${kube[@]}" -n "$namespace" get secret platform-demo-registry -o name 2>/dev/null
  ) || fail 'environment-foundation'
  [[ "$pull_secret_name" == 'secret/platform-demo-registry' ]] || \
    fail 'environment-foundation'

  if ! "$python_bin" -c '
import json, sys
environment, namespace = sys.argv[1:3]
ns = json.load(open(sys.argv[3], encoding="utf-8"))
items = ns.get("items", [])
selected = [item for item in items if item.get("metadata", {}).get("name") == namespace]
assert len(selected) == 1
labels = selected[0].get("metadata", {}).get("labels", {})
assert labels == {
    "app.kubernetes.io/part-of": "platform-demo",
    "kubernetes.io/metadata.name": namespace,
    "platform.verda-demo.io/environment": environment,
    "platform.verda-demo.io/owner": "platform-team",
    "platform.verda-demo.io/topology": "platform-management-cluster",
    "pod-security.kubernetes.io/enforce": "restricted",
    "pod-security.kubernetes.io/enforce-version": "v1.35",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/audit-version": "v1.35",
    "pod-security.kubernetes.io/warn": "restricted",
    "pod-security.kubernetes.io/warn-version": "v1.35",
}
quota = json.load(open(sys.argv[4], encoding="utf-8"))
expected_quota = {
    "dev": {"requests.cpu":"500m","requests.memory":"1Gi","limits.cpu":"2","limits.memory":"2Gi","pods":"10","persistentvolumeclaims":"2"},
    "staging": {"requests.cpu":"500m","requests.memory":"1Gi","limits.cpu":"2","limits.memory":"2Gi","pods":"10","persistentvolumeclaims":"2"},
    "prod": {"requests.cpu":"1","requests.memory":"2Gi","limits.cpu":"4","limits.memory":"4Gi","pods":"16","persistentvolumeclaims":"2"},
}[environment]
assert quota.get("metadata", {}).get("name") == "platform-budget"
assert quota.get("spec", {}).get("hard") == expected_quota
limits = json.load(open(sys.argv[5], encoding="utf-8"))
assert limits.get("metadata", {}).get("name") == "workload-defaults"
assert limits.get("spec", {}).get("limits") == [{
    "type":"Container",
    "default":{"cpu":"250m","memory":"256Mi"},
    "defaultRequest":{"cpu":"50m","memory":"64Mi"},
    "max":{"cpu":"1","memory":"1Gi"},
}]
policies = json.load(open(sys.argv[6], encoding="utf-8")).get("items", [])
by_name = {item.get("metadata", {}).get("name"): item for item in policies}
assert set(by_name) == {"default-deny", "allow-cluster-dns"}
deny = by_name["default-deny"].get("spec", {})
assert deny.get("podSelector") == {} and set(deny.get("policyTypes", [])) == {"Ingress", "Egress"}
assert deny.get("ingress", []) == [] and deny.get("egress", []) == []
dns = by_name["allow-cluster-dns"].get("spec", {})
assert dns.get("podSelector") == {} and dns.get("policyTypes") == ["Egress"]
egress = dns.get("egress", [])
assert len(egress) == 1
assert egress[0].get("to") == [{
    "namespaceSelector":{"matchLabels":{"kubernetes.io/metadata.name":"kube-system"}},
    "podSelector":{"matchLabels":{"k8s-app":"kube-dns"}},
}]
assert {tuple(sorted(port.items())) for port in egress[0].get("ports", [])} == {
    (("port", 53), ("protocol", "TCP")),
    (("port", 53), ("protocol", "UDP")),
}
service_account = json.load(open(sys.argv[7], encoding="utf-8"))
assert service_account.get("metadata", {}).get("name") == "platform-demo"
assert service_account.get("automountServiceAccountToken") is False
assert service_account.get("imagePullSecrets") == [{"name":"platform-demo-registry"}]
binding = json.load(open(sys.argv[8], encoding="utf-8"))
assert binding.get("metadata", {}).get("name") == "verda-reviewers-view"
assert binding.get("subjects") == [{"kind":"Group","apiGroup":"rbac.authorization.k8s.io","name":"verda-reviewers"}]
assert binding.get("roleRef") == {"kind":"ClusterRole","apiGroup":"rbac.authorization.k8s.io","name":"view"}
' "$environment" "$namespace" "$namespace_json" "$quota_json" "$limits_json" \
    "$policies_json" "$service_account_json" "$role_binding_json" >/dev/null 2>&1; then
    fail 'environment-foundation'
  fi
done
printf '[PASS] environment-foundations=3 labels=exact quota=true limitrange=true network-default-deny=true dns=true rbac=true pull-secret=present\n'

sealed_status=$(
  "${kube[@]}" -n sealed-secrets get sealedsecret phase6-reconciliation-test \
    -o 'jsonpath={range .status.conditions[*]}{.type}={.status}{"\n"}{end}' 2>/dev/null
) || fail 'sealed-secret-reconciliation'
[[ "$sealed_status" == *'Synced=True'* ]] || fail 'sealed-secret-reconciliation'
sealed_secret_name=$(
  "${kube[@]}" -n sealed-secrets get secret phase6-reconciliation-test -o name 2>/dev/null
) || fail 'sealed-secret-reconciliation'
[[ "$sealed_secret_name" == 'secret/phase6-reconciliation-test' ]] || \
  fail 'sealed-secret-reconciliation'
unset sealed_status sealed_secret_name pull_secret_name
printf '[PASS] sealed-secret-reconciled=1 secret-data-read=false\n'

cluster_policies_json="$runtime_dir/cluster-policies.json"
policy_reports_json="$runtime_dir/policy-reports.json"
cluster_policy_reports_json="$runtime_dir/cluster-policy-reports.json"
kube_json "$cluster_policies_json" get clusterpolicy \
  workload-baseline sealed-secret-strict-scope
kube_json "$policy_reports_json" get policyreports.wgpolicyk8s.io --all-namespaces
kube_json "$cluster_policy_reports_json" get clusterpolicyreports.wgpolicyk8s.io
if ! "$python_bin" -c '
import json, sys
policies = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
assert {p.get("metadata", {}).get("name") for p in policies} == {
    "workload-baseline", "sealed-secret-strict-scope"
}
for policy in policies:
    spec = policy.get("spec", {})
    assert spec.get("validationFailureAction") == "Audit"
    assert spec.get("background") is True and spec.get("failurePolicy") == "Ignore"
    status = policy.get("status", {})
    ready = status.get("ready") is True or any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )
    assert ready
reports = json.load(open(sys.argv[2], encoding="utf-8")).get("items", [])
cluster_reports = json.load(open(sys.argv[3], encoding="utf-8")).get("items", [])
assert isinstance(cluster_reports, list)
required = {"demo-dev", "demo-staging", "demo-prod"}
covered = set()
for report in reports:
    namespace = report.get("metadata", {}).get("namespace")
    results = report.get("results", [])
    total = sum(int(value) for value in report.get("summary", {}).values())
    if namespace in required and any(r.get("policy") == "workload-baseline" for r in results):
        assert total > 0
        assert all(r.get("result") in {"pass", "fail", "warn", "skip", "error"} for r in results)
        covered.add(namespace)
assert covered == required
' "$cluster_policies_json" "$policy_reports_json" "$cluster_policy_reports_json" \
  >/dev/null 2>&1; then
  fail 'kyverno-audit-reports'
fi
printf '[PASS] kyverno-policies=2 mode=audit background=true environment-reports=3\n'

bsl_json="$runtime_dir/backup-storage-locations.json"
kube_json "$bsl_json" -n velero get backupstoragelocations.velero.io management-s3
if ! "$python_bin" -c '
import json, sys
item = json.load(open(sys.argv[1], encoding="utf-8"))
assert item.get("metadata", {}).get("name") == "management-s3"
status = item.get("status", {})
assert status.get("phase") == "Available" and status.get("lastValidationTime")
' "$bsl_json" >/dev/null 2>&1; then
  fail 'velero-bsl'
fi
printf '[PASS] velero-bsl=available locations=1\n'

application_digest_file="$runtime_dir/application.digest"
private_output "$application_digest_file"
for index in "${!namespaces[@]}"; do
  environment=${environments[index]}
  namespace=${namespaces[index]}
  expected=${expected_replicas[index]}
  deployment_json="$runtime_dir/${environment}-deployment.json"
  ingresses_json="$runtime_dir/${environment}-ingresses.json"
  certificates_json="$runtime_dir/${environment}-certificates.json"
  kube_json "$deployment_json" -n "$namespace" get deployment platform-demo
  kube_json "$ingresses_json" -n "$namespace" get ingress
  kube_json "$certificates_json" -n "$namespace" get certificate
  app_digest=$(
    "$python_bin" -c '
import json, re, sys, urllib.parse
environment, expected, endpoint, registry_endpoint = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
deployment = json.load(open(sys.argv[5], encoding="utf-8"))
metadata, spec, status = deployment["metadata"], deployment["spec"], deployment["status"]
assert metadata.get("name") == "platform-demo"
assert spec.get("replicas") == expected
assert status.get("observedGeneration") == metadata.get("generation")
assert status.get("updatedReplicas") == expected
assert status.get("readyReplicas") == expected
assert status.get("availableReplicas") == expected
assert status.get("unavailableReplicas", 0) == 0
pod = spec.get("template", {}).get("spec", {})
assert pod.get("serviceAccountName") == "platform-demo"
containers = pod.get("containers", [])
assert len(containers) == 1
host = urllib.parse.urlparse(endpoint).hostname
registry_host = urllib.parse.urlparse(registry_endpoint).hostname
pattern = rf"{re.escape(registry_host)}/platform-demo/platform-demo@(sha256:[0-9a-f]{{64}})"
match = re.fullmatch(pattern, containers[0].get("image", ""))
assert match and match.group(1) != "sha256:" + "0" * 64
ingresses = json.load(open(sys.argv[6], encoding="utf-8")).get("items", [])
selected = [item for item in ingresses if item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") == "platform-demo"]
assert len(selected) == 1
ingress = selected[0].get("spec", {})
assert ingress.get("ingressClassName") == "traefik"
assert [rule.get("host") for rule in ingress.get("rules", [])] == [host]
tls = ingress.get("tls", [])
assert len(tls) == 1 and tls[0].get("hosts") == [host]
secret = tls[0].get("secretName")
assert secret
certificates = json.load(open(sys.argv[7], encoding="utf-8")).get("items", [])
selected = [item for item in certificates if item.get("spec", {}).get("secretName") == secret]
assert len(selected) == 1
certificate = selected[0]
assert certificate.get("spec", {}).get("dnsNames") == [host]
assert any(c.get("type") == "Ready" and c.get("status") == "True" for c in certificate.get("status", {}).get("conditions", []))
print(match.group(1))
' "$environment" "$expected" "${application_endpoints[index]}" "$harbor_endpoint" \
      "$deployment_json" "$ingresses_json" "$certificates_json" 2>/dev/null
  ) || fail 'application-runtime'
  if [[ $index -eq 0 ]]; then
    printf '%s\n' "$app_digest" >"$application_digest_file"
  else
    [[ "$app_digest" == "$(<"$application_digest_file")" ]] || fail 'application-runtime'
  fi
  app_response="$runtime_dir/${environment}-response.json"
  private_output "$app_response"
  "$curl_bin" --silent --show-error --fail --max-redirs 0 --max-time 20 \
    --proto '=https' --tlsv1.2 --output "$app_response" \
    "${application_endpoints[index]}/" 2>/dev/null || fail 'application-tls'
  if ! "$python_bin" -c '
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("service") == "platform-demo"
assert payload.get("environment") == sys.argv[2]
' "$app_response" "$environment" >/dev/null 2>&1; then
    fail 'application-tls'
  fi
  unset app_digest
done
printf '[PASS] applications=3 replicas=1-1-2 immutable-image=one-digest tls-endpoints=3\n'

rancher_clusters="$runtime_dir/rancher-clusters.json"
rancher_user="$runtime_dir/rancher-user.json"
api_get "$rancher_endpoint" "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" \
  '/v3/clusters?name=local' "$rancher_clusters"
api_get "$rancher_endpoint" "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" \
  '/v3/users?me=true' "$rancher_user"
if ! reviewer_id=$(
  "$python_bin" -c '
import json, re, sys
clusters = json.load(open(sys.argv[1], encoding="utf-8")).get("data", [])
local = [c for c in clusters if c.get("id") == "local" or c.get("name") == "local"]
assert len(local) == 1 and str(local[0].get("state", "")).lower() == "active"
users = json.load(open(sys.argv[2], encoding="utf-8")).get("data", [])
current = [u for u in users if u.get("me") is True]
assert len(current) == 1
user = current[0]
assert user.get("username") == "verda-reviewer" and user.get("enabled") is True
identifier = user.get("id", "")
assert re.fullmatch(r"[A-Za-z0-9:._-]+", identifier)
print(identifier)
' "$rancher_clusters" "$rancher_user" 2>/dev/null
); then
  fail 'rancher-reviewer'
fi
role_response="$runtime_dir/rancher-roles.json"
role_status=$(api_status "$rancher_endpoint" "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" \
  "/v3/globalrolebindings?userId=${reviewer_id}" "$role_response") || fail 'rancher-reviewer'
case "$role_status" in
  403) ;;
  200)
    if ! "$python_bin" -c '
import json, sys
items = json.load(open(sys.argv[1], encoding="utf-8")).get("data", [])
for item in items:
    role = str(item.get("globalRoleId", "")).lower()
    assert role not in {"admin", "administrator", "restricted-admin", "global-admin"}
' "$role_response" >/dev/null 2>&1; then
      fail 'rancher-reviewer'
    fi
    ;;
  *) fail 'rancher-reviewer' ;;
esac
unset reviewer_id role_status
for index in "${!namespaces[@]}"; do
  rancher_workload="$runtime_dir/rancher-${environments[index]}-workload.json"
  api_get "$rancher_endpoint" "$PHASE6_RANCHER_REVIEWER_TOKEN_FILE" \
    "/k8s/clusters/local/apis/apps/v1/namespaces/${namespaces[index]}/deployments/platform-demo" \
    "$rancher_workload"
  if ! "$python_bin" -c '
import json, sys
item = json.load(open(sys.argv[1], encoding="utf-8"))
expected = int(sys.argv[2])
assert item.get("metadata", {}).get("name") == "platform-demo"
assert item.get("spec", {}).get("replicas") == expected
assert item.get("status", {}).get("readyReplicas") == expected
' "$rancher_workload" "${expected_replicas[index]}" >/dev/null 2>&1; then
    fail 'rancher-visibility'
  fi
done
printf '[PASS] rancher-cluster=active workload-visibility=3 reviewer-non-admin=true direct-kubeconfig-independent=true\n'

harbor_project="$runtime_dir/harbor-project.json"
harbor_artifacts="$runtime_dir/harbor-artifacts.json"
api_get "$harbor_endpoint" "$PHASE6_HARBOR_REVIEWER_TOKEN_FILE" \
  '/api/v2.0/projects/platform-demo' "$harbor_project"
api_get "$harbor_endpoint" "$PHASE6_HARBOR_REVIEWER_TOKEN_FILE" \
  '/api/v2.0/projects/platform-demo/repositories/platform-demo/artifacts?page=1&page_size=25&with_scan_overview=true' \
  "$harbor_artifacts"
if ! "$python_bin" -c '
import json, pathlib, sys
project = json.load(open(sys.argv[1], encoding="utf-8"))
assert project.get("name") == "platform-demo"
metadata = project.get("metadata", {})
assert metadata.get("public") == "false" and metadata.get("auto_scan") == "true"
digest = pathlib.Path(sys.argv[3]).read_text(encoding="utf-8").strip()
artifacts = json.load(open(sys.argv[2], encoding="utf-8"))
selected = [item for item in artifacts if item.get("digest") == digest]
assert len(selected) == 1
overview = selected[0].get("scan_overview", {})
reports = list(overview.values())
assert len(reports) >= 1
completed = [report for report in reports if report.get("scan_status") == "Success"]
assert completed
for report in completed:
    counts = report.get("summary", {}).get("summary", {})
    assert int(counts.get("Critical", 0)) == 0
' "$harbor_project" "$harbor_artifacts" "$application_digest_file" >/dev/null 2>&1; then
  fail 'harbor-artifact'
fi
artifact_digest=$(<"$application_digest_file")
harbor_vulnerabilities="$runtime_dir/harbor-vulnerabilities.json"
api_get "$harbor_endpoint" "$PHASE6_HARBOR_REVIEWER_TOKEN_FILE" \
  "/api/v2.0/projects/platform-demo/repositories/platform-demo/artifacts/${artifact_digest}/additions/vulnerabilities" \
  "$harbor_vulnerabilities"
unset artifact_digest
if ! "$python_bin" -c '
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
scanner = report.get("scanner", {})
identity = " ".join(str(scanner.get(key, "")) for key in ("name", "vendor")).lower()
assert "trivy" in identity or "aqua" in identity
assert all(str(item.get("severity", "")).lower() != "critical" for item in report.get("vulnerabilities", []))
' "$harbor_vulnerabilities" >/dev/null 2>&1; then
  fail 'harbor-trivy'
fi
printf '[PASS] harbor-project=private artifact=digest-matched trivy-scan=complete critical-findings=0\n'

prometheus_services="$runtime_dir/prometheus-services.json"
kube_json "$prometheus_services" -n monitoring get service
prometheus_service=$(
  "$python_bin" -c '
import json, re, sys
items = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
selected = []
for item in items:
    labels = item.get("metadata", {}).get("labels", {})
    ports = item.get("spec", {}).get("ports", [])
    if labels.get("app.kubernetes.io/name") == "prometheus" and any(p.get("port") == 9090 for p in ports):
        selected.append(item.get("metadata", {}).get("name"))
assert len(selected) == 1 and re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", selected[0])
print(selected[0])
' "$prometheus_services" 2>/dev/null
) || fail 'prometheus-service'
prometheus_proxy="/api/v1/namespaces/monitoring/services/http:${prometheus_service}:9090/proxy"
unset prometheus_service
prometheus_targets="$runtime_dir/prometheus-targets.json"
kube_raw "$prometheus_targets" "${prometheus_proxy}/api/v1/targets?state=active"
if ! "$python_bin" -c '
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "success"
targets = payload.get("data", {}).get("activeTargets", [])
assert targets and all(target.get("health") == "up" for target in targets)
required = {"argocd","cattle-system","harbor","kyverno","longhorn-system","monitoring","sealed-secrets","velero","logging","loki","demo-dev","demo-staging","demo-prod"}
covered = {target.get("labels", {}).get("namespace") for target in targets}
assert required <= covered
required_services = {
    ("argocd", "argocd-application-controller-metrics"),
    ("argocd", "argocd-applicationset-controller-metrics"),
    ("argocd", "argocd-repo-server-metrics"),
    ("argocd", "argocd-server-metrics"),
    ("cattle-system", "rancher"),
    ("harbor", "harbor-core"),
    ("harbor", "harbor-exporter"),
    ("harbor", "harbor-jobservice"),
    ("harbor", "harbor-registry"),
    ("longhorn-system", "longhorn-backend"),
    ("kube-system", "rke2-traefik-metrics"),
}
observed_services = {
    (target.get("labels", {}).get("namespace"), target.get("labels", {}).get("service"))
    for target in targets
}
assert required_services <= observed_services
' "$prometheus_targets" >/dev/null 2>&1; then
  fail 'prometheus-targets'
fi

metric_query='sum by (environment) (platform_demo_build_info)'
encoded_metric_query=$(
  "$python_bin" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' \
    "$metric_query" 2>/dev/null
) || fail 'prometheus-metric'
prometheus_metric="$runtime_dir/prometheus-metric.json"
kube_raw "$prometheus_metric" "${prometheus_proxy}/api/v1/query?query=${encoded_metric_query}"
unset prometheus_proxy
if ! "$python_bin" -c '
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "success"
result = payload.get("data", {}).get("result", [])
values = {item.get("metric", {}).get("environment"): float(item.get("value", [0, "0"])[1]) for item in result}
assert values == {"dev": 1.0, "staging": 1.0, "prod": 2.0}
' "$prometheus_metric" >/dev/null 2>&1; then
  fail 'prometheus-metric'
fi
printf '[PASS] prometheus-targets=all-up platform-target-classes=13 required-service-targets=11 application-series=3\n'

grafana_prometheus="$runtime_dir/grafana-prometheus-datasource.json"
grafana_loki="$runtime_dir/grafana-loki-datasource.json"
api_get "$grafana_endpoint" "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" \
  '/api/datasources/uid/prometheus' "$grafana_prometheus"
api_get "$grafana_endpoint" "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" \
  '/api/datasources/uid/loki' "$grafana_loki"
if ! "$python_bin" -c '
import json, sys
prometheus = json.load(open(sys.argv[1], encoding="utf-8"))
loki = json.load(open(sys.argv[2], encoding="utf-8"))
assert prometheus.get("uid") == "prometheus" and prometheus.get("type") == "prometheus"
assert prometheus.get("access") == "proxy"
assert prometheus.get("url") == "http://monitoring-kube-prometheus-prometheus.monitoring:9090/"
assert loki.get("uid") == "loki" and loki.get("type") == "loki" and loki.get("access") == "proxy"
assert loki.get("url") == "http://loki-gateway.loki.svc.cluster.local"
' "$grafana_prometheus" "$grafana_loki" >/dev/null 2>&1; then
  fail 'grafana-datasources'
fi
grafana_prometheus_query="$runtime_dir/grafana-prometheus-query.json"
api_get "$grafana_endpoint" "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" \
  "/api/datasources/proxy/uid/prometheus/api/v1/query?query=${encoded_metric_query}" \
  "$grafana_prometheus_query"
if ! "$python_bin" -c '
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "success"
result = payload.get("data", {}).get("result", [])
values = {item.get("metric", {}).get("environment"): float(item.get("value", [0, "0"])[1]) for item in result}
assert values == {"dev": 1.0, "staging": 1.0, "prod": 2.0}
' "$grafana_prometheus_query" >/dev/null 2>&1; then
  fail 'grafana-prometheus-query'
fi
unset encoded_metric_query metric_query

loki_query='sum(count_over_time({cluster="management", namespace="demo-dev", application="platform-demo"} |= "\"marker\":\"platform_demo\"" [15m]))'
encoded_loki_query=$(
  "$python_bin" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' \
    "$loki_query" 2>/dev/null
) || fail 'grafana-loki-query'
grafana_loki_query="$runtime_dir/grafana-loki-query.json"
api_get "$grafana_endpoint" "$PHASE6_GRAFANA_REVIEWER_TOKEN_FILE" \
  "/api/datasources/proxy/uid/loki/loki/api/v1/query?query=${encoded_loki_query}" \
  "$grafana_loki_query"
unset encoded_loki_query loki_query
if ! "$python_bin" -c '
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "success"
result = payload.get("data", {}).get("result", [])
assert result and sum(float(item.get("value", [0, "0"])[1]) for item in result) > 0
' "$grafana_loki_query" >/dev/null 2>&1; then
  fail 'grafana-loki-query'
fi
printf '[PASS] grafana-datasources=2 datasource-queries=2 demo-dev-log-marker=present raw-logs-read=false\n'

if ! "$python_bin" -c '
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {
    "schema_version", "status", "component_count", "rendered_document_count",
    "workload_definition_count", "pvc_definition_count", "new_steady_cpu_millicores",
    "new_rollout_peak_cpu_millicores", "one_node_loss_rollout_cpu_headroom_millicores",
    "new_steady_memory_bytes", "new_rollout_peak_memory_bytes",
    "one_node_loss_rollout_memory_headroom_bytes", "new_logical_pvc_bytes",
    "new_raw_pvc_bytes", "one_node_loss_pvc_bytes", "storage_headroom_bytes",
    "one_node_loss_storage_headroom_bytes",
}
assert set(report) == expected
assert report["schema_version"] == 1 and report["status"] == "PASS"
assert report["component_count"] == 10
for key in (
    "rendered_document_count", "workload_definition_count", "pvc_definition_count",
    "one_node_loss_rollout_cpu_headroom_millicores",
    "one_node_loss_rollout_memory_headroom_bytes", "one_node_loss_storage_headroom_bytes",
):
    assert isinstance(report[key], int) and report[key] > 0
assert report["new_rollout_peak_cpu_millicores"] >= report["new_steady_cpu_millicores"] > 0
assert report["new_rollout_peak_memory_bytes"] >= report["new_steady_memory_bytes"] > 0
assert report["new_raw_pvc_bytes"] >= report["one_node_loss_pvc_bytes"] >= report["new_logical_pvc_bytes"] > 0
' "$PHASE6_CAPACITY_EVIDENCE_FILE" >/dev/null 2>&1; then
  fail 'one-node-loss-capacity'
fi
printf '[PASS] one-node-loss-capacity=admitted stage-b-dependency=false\n'
printf '[PASS] Phase 6 Platform runtime acceptance completed.\n'
