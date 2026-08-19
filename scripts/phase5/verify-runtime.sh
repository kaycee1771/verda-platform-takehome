#!/usr/bin/env bash
set -Eeuo pipefail
set +x

# Read-only Phase 5 acceptance verifier. All inputs that carry credentials or
# endpoint inventories stay outside Git, every client is pinned to an explicit
# target, and only fixed labels plus aggregate scalars reach stdout/stderr.

fail() {
  printf '[FAIL] gate=%s\n' "$1" >&2
  exit 1
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail 'required-input'
}

require_protected_file() {
  local path="$1"
  local mode owner
  [[ "${path}" == /* && -f "${path}" && ! -L "${path}" ]] || fail 'protected-file'
  mode=$(stat -c '%a' -- "${path}" 2>/dev/null) || fail 'protected-file'
  owner=$(stat -c '%u' -- "${path}" 2>/dev/null) || fail 'protected-file'
  [[ "${mode}" == '600' && "${owner}" == "$(id -u)" ]] || fail 'protected-file'
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail 'dependency'
}

normalize_permission() {
  tr -d '\r\n[:space:]' | tr '[:upper:]' '[:lower:]'
}

require_permission() {
  local token="$1"
  local expected="$2"
  local action="$3"
  local result
  if ! result=$(
    ARGOCD_AUTH_TOKEN="${token}" "${argocd_base[@]}" \
      account can-i "${action}" applications '*' 2>/dev/null | normalize_permission
  ); then
    fail 'argocd-rbac'
  fi
  [[ "${result}" == "${expected}" ]] || fail 'argocd-rbac'
}

tcp_open() {
  local address="$1"
  local port="$2"
  "${timeout_bin}" 4s "${nc_bin}" -z -w 2 "${address}" "${port}" \
    >/dev/null 2>&1
}

cleanup() {
  if [[ -n "${runtime_dir:-}" && -d "${runtime_dir}" && \
        "$(basename -- "${runtime_dir}")" == verda-phase5.* ]]; then
    rm -rf -- "${runtime_dir}"
  fi
}

for name in \
  PHASE5_KUBECONFIG \
  PHASE5_KUBE_CONTEXT \
  PHASE5_PUBLIC_HOST \
  PHASE5_ARGO_ROOT_APP \
  PHASE5_ARGO_EXPECTED_CHILDREN \
  PHASE5_ARGOCD_ADMIN_TOKEN_FILE \
  PHASE5_ARGOCD_REVIEWER_TOKEN_FILE \
  PHASE5_ARGOCD_ADMIN_SUBJECT \
  PHASE5_ARGOCD_REVIEWER_SUBJECT \
  PHASE5_EXTERNAL_ENDPOINTS_FILE \
  PHASE5_HTTP_MODE; do
  require_value "${name}"
done

kubectl_bin=${PHASE5_KUBECTL_BIN:-kubectl}
argocd_bin=${PHASE5_ARGOCD_BIN:-argocd}
curl_bin=${PHASE5_CURL_BIN:-curl}
openssl_bin=${PHASE5_OPENSSL_BIN:-openssl}
nc_bin=${PHASE5_NC_BIN:-nc}
timeout_bin=${PHASE5_TIMEOUT_BIN:-timeout}
python_bin=${PHASE5_PYTHON_BIN:-python3}
date_bin=${PHASE5_DATE_BIN:-date}

for binary in \
  "${kubectl_bin}" "${argocd_bin}" "${curl_bin}" "${openssl_bin}" \
  "${nc_bin}" "${timeout_bin}" "${python_bin}" "${date_bin}" stat id; do
  require_command "${binary}"
done

require_protected_file "${PHASE5_KUBECONFIG}"
require_protected_file "${PHASE5_ARGOCD_ADMIN_TOKEN_FILE}"
require_protected_file "${PHASE5_ARGOCD_REVIEWER_TOKEN_FILE}"
require_protected_file "${PHASE5_EXTERNAL_ENDPOINTS_FILE}"

[[ "${PHASE5_KUBE_CONTEXT}" =~ ^[A-Za-z0-9._@:/-]+$ ]] || fail 'kube-context'
[[ "${PHASE5_PUBLIC_HOST}" =~ ^argocd\.[0-9]{1,3}(-[0-9]{1,3}){3}\.sslip\.io$ ]] || \
  fail 'public-hostname'
[[ "${PHASE5_ARGO_ROOT_APP}" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]] || \
  fail 'argocd-application-input'
[[ "${PHASE5_ARGO_EXPECTED_CHILDREN}" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?(,[a-z0-9]([-a-z0-9.]*[a-z0-9])?)*$ ]] || \
  fail 'argocd-application-input'
[[ "${PHASE5_HTTP_MODE}" == 'acme-only' ]] || fail 'http-mode'
[[ ${#PHASE5_ARGOCD_ADMIN_SUBJECT} -le 128 && \
   "${PHASE5_ARGOCD_ADMIN_SUBJECT}" != *[[:space:]]* ]] || fail 'argocd-subject'
[[ ${#PHASE5_ARGOCD_REVIEWER_SUBJECT} -le 128 && \
   "${PHASE5_ARGOCD_REVIEWER_SUBJECT}" != *[[:space:]]* && \
   "${PHASE5_ARGOCD_REVIEWER_SUBJECT}" != "${PHASE5_ARGOCD_ADMIN_SUBJECT}" ]] || \
  fail 'argocd-subject'

if ! "${python_bin}" -c '
import ipaddress, re, sys
host = sys.argv[1]
encoded = re.fullmatch(r"argocd\.([0-9]{1,3}(?:-[0-9]{1,3}){3})\.sslip\.io", host)
assert encoded
ipaddress.IPv4Address(encoded.group(1).replace("-", "."))
' "${PHASE5_PUBLIC_HOST}" >/dev/null 2>&1; then
  fail 'public-hostname'
fi

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/verda-phase5.XXXXXX") || fail 'runtime-directory'
trap cleanup EXIT
chmod 700 "${runtime_dir}" || fail 'runtime-directory'

kube=(
  "${kubectl_bin}"
  --kubeconfig "${PHASE5_KUBECONFIG}"
  --context "${PHASE5_KUBE_CONTEXT}"
  --request-timeout=20s
)

if ! configured_context=$("${kube[@]}" config current-context 2>/dev/null); then
  fail 'kube-context'
fi
[[ "${configured_context}" == "${PHASE5_KUBE_CONTEXT}" ]] || fail 'kube-context'
if ! selected_context=$(
  "${kube[@]}" config get-contexts "${PHASE5_KUBE_CONTEXT}" -o name 2>/dev/null
); then
  fail 'kube-context'
fi
[[ "${selected_context}" == "${PHASE5_KUBE_CONTEXT}" ]] || fail 'kube-context'
printf '[PASS] kube-context=explicit kubeconfig-mode=0600\n'

if ! applications_json=$(
  "${kube[@]}" -n argocd get applications.argoproj.io -o json 2>/dev/null
); then
  fail 'argocd-applications'
fi
if ! application_counts=$(
  "${python_bin}" -c '
import json, sys
root = sys.argv[1]
children = sys.argv[2].split(",")
assert len(children) == len(set(children)) and root not in children
items = json.load(sys.stdin).get("items", [])
by_name = {item.get("metadata", {}).get("name"): item for item in items}
assert len(by_name) == len(items)
expected = [root, *children]
assert all(name in by_name for name in expected)
for name in expected:
    status = by_name[name].get("status", {})
    assert status.get("health", {}).get("status") == "Healthy"
    assert status.get("sync", {}).get("status") == "Synced"
print(len(expected), len(children))
' "${PHASE5_ARGO_ROOT_APP}" "${PHASE5_ARGO_EXPECTED_CHILDREN}" \
    <<<"${applications_json}" 2>/dev/null
); then
  fail 'argocd-applications'
fi
read -r application_count child_count <<<"${application_counts}"
[[ "${application_count}" =~ ^[0-9]+$ && "${child_count}" =~ ^[0-9]+$ ]] || \
  fail 'argocd-applications'
printf '[PASS] argocd-applications=%s children=%s healthy=%s synced=%s\n' \
  "${application_count}" "${child_count}" "${application_count}" "${application_count}"

if ! deployments_json=$(
  "${kube[@]}" -n cert-manager get deployment \
    cert-manager cert-manager-webhook cert-manager-cainjector -o json 2>/dev/null
); then
  fail 'cert-manager-readiness'
fi
if ! ready_replicas=$(
  "${python_bin}" -c '
import json, sys
expected = {"cert-manager", "cert-manager-webhook", "cert-manager-cainjector"}
items = json.load(sys.stdin).get("items", [])
assert {item.get("metadata", {}).get("name") for item in items} == expected
ready = 0
for item in items:
    metadata = item.get("metadata", {})
    spec = item.get("spec", {})
    status = item.get("status", {})
    desired = spec.get("replicas")
    assert desired == 2
    assert status.get("observedGeneration") == metadata.get("generation")
    assert status.get("replicas") == desired
    assert status.get("updatedReplicas") == desired
    assert status.get("readyReplicas") == desired
    assert status.get("availableReplicas") == desired
    assert status.get("unavailableReplicas", 0) == 0
    ready += desired
print(ready)
' <<<"${deployments_json}" 2>/dev/null
); then
  fail 'cert-manager-readiness'
fi
[[ "${ready_replicas}" == '6' ]] || fail 'cert-manager-readiness'
printf '[PASS] cert-manager-components=3 ready-replicas=%s\n' "${ready_replicas}"

if ! certificates_json=$(
  "${kube[@]}" -n argocd get certificate \
    argocd-staging argocd-production -o json 2>/dev/null
); then
  fail 'certificate-readiness'
fi
if ! issuers_json=$(
  "${kube[@]}" -n argocd get issuer \
    letsencrypt-staging letsencrypt-production -o json 2>/dev/null
); then
  fail 'certificate-readiness'
fi
if ! "${python_bin}" -c '
import json, sys
host = sys.argv[1]
certs = json.loads(sys.argv[2]).get("items", [])
issuers = json.load(sys.stdin).get("items", [])
cert_expected = {
    "argocd-staging": ("argocd-staging-tls", "letsencrypt-staging"),
    "argocd-production": ("argocd-ingress-tls", "letsencrypt-production"),
}
issuer_expected = {
    "letsencrypt-staging": "https://acme-staging-v02.api.letsencrypt.org/directory",
    "letsencrypt-production": "https://acme-v02.api.letsencrypt.org/directory",
}
assert {item.get("metadata", {}).get("name") for item in certs} == set(cert_expected)
assert {item.get("metadata", {}).get("name") for item in issuers} == set(issuer_expected)
def ready(item):
    return any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in item.get("status", {}).get("conditions", []))
for item in certs:
    name = item["metadata"]["name"]
    secret, issuer = cert_expected[name]
    spec = item.get("spec", {})
    assert ready(item)
    assert spec.get("secretName") == secret
    assert spec.get("dnsNames") == [host]
    assert spec.get("issuerRef") == {
        "group": "cert-manager.io", "kind": "Issuer", "name": issuer
    }
for item in issuers:
    name = item["metadata"]["name"]
    assert ready(item)
    assert item.get("spec", {}).get("acme", {}).get("server") == issuer_expected[name]
' "${PHASE5_PUBLIC_HOST}" "${certificates_json}" <<<"${issuers_json}" 2>/dev/null; then
  fail 'certificate-readiness'
fi
printf '[PASS] certificates=2 issuers=2 ready=true issuer-refs=exact\n'

if ! ingresses_json=$(
  "${kube[@]}" get ingress --all-namespaces -o json 2>/dev/null
); then
  fail 'http-route-boundary'
fi
if ! "${python_bin}" -c '
import json, sys
host = sys.argv[1]
items = json.load(sys.stdin).get("items", [])
application = None
for item in items:
    metadata = item.get("metadata", {})
    annotations = metadata.get("annotations", {})
    labels = metadata.get("labels", {})
    spec = item.get("spec", {})
    if metadata.get("namespace") == "argocd" and metadata.get("name") == "argocd-server":
        application = item
    entrypoints = {
        value.strip()
        for value in annotations.get(
            "traefik.ingress.kubernetes.io/router.entrypoints", ""
        ).split(",")
        if value.strip()
    }
    if "web" in entrypoints:
        assert labels.get("acme.cert-manager.io/http01-solver") == "true"
assert application is not None
metadata = application["metadata"]
spec = application["spec"]
assert spec.get("ingressClassName") == "traefik"
assert metadata.get("annotations", {}).get(
    "traefik.ingress.kubernetes.io/router.entrypoints"
) == "websecure"
assert spec.get("tls") == [{"hosts": [host], "secretName": "argocd-ingress-tls"}]
assert [rule.get("host") for rule in spec.get("rules", [])] == [host]
' "${PHASE5_PUBLIC_HOST}" <<<"${ingresses_json}" 2>/dev/null; then
  fail 'http-route-boundary'
fi

certificate_file="${runtime_dir}/public-leaf.pem"
if ! "${timeout_bin}" 20s "${openssl_bin}" s_client \
  -connect "${PHASE5_PUBLIC_HOST}:443" \
  -servername "${PHASE5_PUBLIC_HOST}" \
  -verify_hostname "${PHASE5_PUBLIC_HOST}" \
  -verify_return_error -showcerts </dev/null 2>/dev/null | \
  "${openssl_bin}" x509 -outform PEM >"${certificate_file}" 2>/dev/null; then
  fail 'tls-inspection'
fi
chmod 600 "${certificate_file}" || fail 'tls-inspection'
if ! hostname_check=$(
  "${openssl_bin}" x509 -in "${certificate_file}" -noout \
    -checkhost "${PHASE5_PUBLIC_HOST}" 2>/dev/null
); then
  fail 'tls-inspection'
fi
[[ "${hostname_check}" == *'does match certificate'* ]] || fail 'tls-inspection'
if ! issuer_line=$(
  "${openssl_bin}" x509 -in "${certificate_file}" -noout -issuer 2>/dev/null
); then
  fail 'tls-inspection'
fi
[[ "${issuer_line}" =~ O[[:space:]]*=[[:space:]]*Let.s[[:space:]]Encrypt ]] || \
  fail 'tls-inspection'
if ! "${openssl_bin}" x509 -in "${certificate_file}" -noout \
  -checkend 604800 >/dev/null 2>&1; then
  fail 'tls-inspection'
fi
if ! end_date_line=$(
  "${openssl_bin}" x509 -in "${certificate_file}" -noout -enddate 2>/dev/null
); then
  fail 'tls-inspection'
fi
[[ "${end_date_line}" == notAfter=* ]] || fail 'tls-inspection'
if ! expiry_epoch=$(
  "${date_bin}" -u -d "${end_date_line#notAfter=}" +%s 2>/dev/null
); then
  fail 'tls-inspection'
fi
if ! now_epoch=$("${date_bin}" -u +%s 2>/dev/null); then
  fail 'tls-inspection'
fi
[[ "${expiry_epoch}" =~ ^[0-9]+$ && "${now_epoch}" =~ ^[0-9]+$ ]] || fail 'tls-inspection'
(( expiry_epoch > now_epoch )) || fail 'tls-inspection'
validity_days=$(( (expiry_epoch - now_epoch) / 86400 ))
(( validity_days >= 7 )) || fail 'tls-inspection'
printf '[PASS] tls-hostname-match=true tls-issuer=letsencrypt tls-validity-days=%s\n' \
  "${validity_days}"

curl_common=(
  "${curl_bin}"
  --silent
  --show-error
  --noproxy '*'
  --connect-timeout 5
  --max-time 20
  --max-redirs 0
  --output /dev/null
  --write-out '%{http_code}'
)
if ! anonymous_code=$(
  "${curl_common[@]}" --proto '=https' \
    "https://${PHASE5_PUBLIC_HOST}/api/v1/applications" 2>/dev/null
); then
  fail 'argocd-anonymous'
fi
[[ "${anonymous_code}" == '401' || "${anonymous_code}" == '403' ]] || \
  fail 'argocd-anonymous'
printf '[PASS] argocd-anonymous=denied\n'

admin_token=$(<"${PHASE5_ARGOCD_ADMIN_TOKEN_FILE}")
reviewer_token=$(<"${PHASE5_ARGOCD_REVIEWER_TOKEN_FILE}")
[[ ${#admin_token} -ge 20 && ${#admin_token} -le 16384 && \
   "${admin_token}" != *[[:space:]]* ]] || fail 'argocd-auth-file'
[[ ${#reviewer_token} -ge 20 && ${#reviewer_token} -le 16384 && \
   "${reviewer_token}" != *[[:space:]]* && "${reviewer_token}" != "${admin_token}" ]] || \
  fail 'argocd-auth-file'

argocd_base=(
  "${argocd_bin}"
  --server "${PHASE5_PUBLIC_HOST}"
  --grpc-web
  --http-retry-max 1
  --loglevel error
  --config "${runtime_dir}/argocd-config"
  --prompts-enabled=false
)

if ! admin_info=$(
  ARGOCD_AUTH_TOKEN="${admin_token}" "${argocd_base[@]}" \
    account get-user-info -o json 2>/dev/null
); then
  fail 'argocd-admin-authentication'
fi
if ! reviewer_info=$(
  ARGOCD_AUTH_TOKEN="${reviewer_token}" "${argocd_base[@]}" \
    account get-user-info -o json 2>/dev/null
); then
  fail 'argocd-reviewer-authentication'
fi
if ! "${python_bin}" -c '
import json, sys
info = json.load(sys.stdin)
assert info.get("loggedIn") is True
assert info.get("username") == sys.argv[1]
' "${PHASE5_ARGOCD_ADMIN_SUBJECT}" <<<"${admin_info}" 2>/dev/null; then
  fail 'argocd-admin-authentication'
fi
if ! "${python_bin}" -c '
import json, sys
info = json.load(sys.stdin)
assert info.get("loggedIn") is True
assert info.get("username") == sys.argv[1]
' "${PHASE5_ARGOCD_REVIEWER_SUBJECT}" <<<"${reviewer_info}" 2>/dev/null; then
  fail 'argocd-reviewer-authentication'
fi

if ! reviewer_apps=$(
  ARGOCD_AUTH_TOKEN="${reviewer_token}" "${argocd_base[@]}" \
    app list -o json 2>/dev/null
); then
  fail 'argocd-reviewer-read'
fi
if ! "${python_bin}" -c '
import json, sys
root = sys.argv[1]
items = json.load(sys.stdin)
assert isinstance(items, list) and items
assert root in {item.get("metadata", {}).get("name") for item in items}
' "${PHASE5_ARGO_ROOT_APP}" <<<"${reviewer_apps}" 2>/dev/null; then
  fail 'argocd-reviewer-read'
fi

require_permission "${admin_token}" yes get
require_permission "${admin_token}" yes sync
require_permission "${reviewer_token}" yes get
require_permission "${reviewer_token}" no sync
require_permission "${reviewer_token}" no action
require_permission "${reviewer_token}" no override
unset admin_token reviewer_token admin_info reviewer_info reviewer_apps
printf '[PASS] argocd-admin=authenticated reviewer=authenticated reviewer-read=true reviewer-sync=false reviewer-action=false\n'

if ! https_code=$(
  "${curl_common[@]}" --proto '=https' "https://${PHASE5_PUBLIC_HOST}/" 2>/dev/null
); then
  fail 'public-https'
fi
[[ "${https_code}" == '200' ]] || fail 'public-https'
if ! http_code=$(
  "${curl_common[@]}" --proto '=http' "http://${PHASE5_PUBLIC_HOST}/" 2>/dev/null
); then
  fail 'public-http'
fi
[[ "${http_code}" == '404' ]] || fail 'public-http'
printf '[PASS] public-https=%s http-mode=acme-only http-status=%s\n' \
  "${https_code}" "${http_code}"

if ! endpoint_lines=$(
  "${python_bin}" -c '
import ipaddress, pathlib, sys
path = pathlib.Path(sys.argv[1])
rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert len(rows) == 3 and len(set(rows)) == 3
addresses = [str(ipaddress.IPv4Address(row)) for row in rows]
host_ip = sys.argv[2].removeprefix("argocd.").removesuffix(".sslip.io").replace("-", ".")
assert str(ipaddress.IPv4Address(host_ip)) in addresses
print("\n".join(addresses))
' "${PHASE5_EXTERNAL_ENDPOINTS_FILE}" "${PHASE5_PUBLIC_HOST}" 2>/dev/null
); then
  fail 'external-endpoints'
fi
mapfile -t external_endpoints <<<"${endpoint_lines}"
[[ ${#external_endpoints[@]} -eq 3 ]] || fail 'external-endpoints'

allowed_tcp=(22 80 443 6443)
denied_tcp=(
  2379 2380 2381 4240 4244 4245 4250 6060 6061 6062 9345
  9878 9879 9890 9891 9893 9901 9962 9963 9964 9965 9966
  10250 10257 10259 30000 31000 32767
)
for address in "${external_endpoints[@]}"; do
  for port in "${allowed_tcp[@]}"; do
    tcp_open "${address}" "${port}" || fail 'external-port-boundary'
  done
  for port in "${denied_tcp[@]}"; do
    if tcp_open "${address}" "${port}"; then
      fail 'external-port-boundary'
    fi
  done
done
printf '[PASS] external-nodes=3 allowed-tcp-classes=%s denied-tcp-classes=%s boundary=exact\n' \
  "${#allowed_tcp[@]}" "${#denied_tcp[@]}"
printf '[PASS] Phase 5 runtime verification completed.\n'
