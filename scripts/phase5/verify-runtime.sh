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

tcp_open() {
  local address="$1"
  local port="$2"
  "${timeout_bin}" 4s "${nc_bin}" -z -w 2 "${address}" "${port}" \
    >/dev/null 2>&1
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
)
readonly argocd_admin_subject='admin'
readonly argocd_reviewer_subject='reviewer'
readonly phase5_http_mode='acme-only'

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
  PHASE5_ARGOCD_ADMIN_TOKEN_FILE \
  PHASE5_ARGOCD_REVIEWER_TOKEN_FILE \
  PHASE5_EXTERNAL_ENDPOINTS_FILE; do
  require_value "${name}"
done

kubectl_bin=${PHASE5_KUBECTL_BIN:-kubectl}
curl_bin=${PHASE5_CURL_BIN:-curl}
openssl_bin=${PHASE5_OPENSSL_BIN:-openssl}
nc_bin=${PHASE5_NC_BIN:-nc}
timeout_bin=${PHASE5_TIMEOUT_BIN:-timeout}
python_bin=${PHASE5_PYTHON_BIN:-python3}
date_bin=${PHASE5_DATE_BIN:-date}

for binary in \
  "${kubectl_bin}" "${curl_bin}" "${openssl_bin}" \
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
children = sys.argv[2:]
assert len(children) == len(set(children)) and root not in children
items = json.load(sys.stdin).get("items", [])
by_name = {item.get("metadata", {}).get("name"): item for item in items}
assert len(by_name) == len(items)
expected = [root, *children]
assert set(by_name) == set(expected) and len(items) == len(expected)
for name in expected:
    status = by_name[name].get("status", {})
    assert status.get("health", {}).get("status") == "Healthy"
    assert status.get("sync", {}).get("status") == "Synced"
print(len(expected), len(children))
' "${argocd_root_app}" "${argocd_child_apps[@]}" \
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

curl_resolve_files=()
for index in "${!external_endpoints[@]}"; do
  resolve_file="${runtime_dir}/endpoint-${index}.curl"
  printf 'resolve = "%s:443:%s"\nresolve = "%s:80:%s"\n' \
    "${PHASE5_PUBLIC_HOST}" "${external_endpoints[index]}" \
    "${PHASE5_PUBLIC_HOST}" "${external_endpoints[index]}" >"${resolve_file}"
  chmod 600 "${resolve_file}" || fail 'external-endpoints'
  curl_resolve_files+=("${resolve_file}")
done

minimum_validity_days=''
certificate_fingerprint=''
for index in "${!external_endpoints[@]}"; do
  certificate_file="${runtime_dir}/public-leaf-${index}.pem"
  if ! "${timeout_bin}" 20s "${openssl_bin}" s_client \
    -connect "${external_endpoints[index]}:443" \
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
  if ! fingerprint_line=$(
    "${openssl_bin}" x509 -in "${certificate_file}" -noout \
      -fingerprint -sha256 2>/dev/null
  ); then
    fail 'tls-inspection'
  fi
  fingerprint=${fingerprint_line#*=}
  [[ "${fingerprint}" =~ ^([0-9A-F]{2}:){31}[0-9A-F]{2}$ ]] || fail 'tls-inspection'
  if [[ -z "${certificate_fingerprint}" ]]; then
    certificate_fingerprint="${fingerprint}"
  else
    [[ "${fingerprint}" == "${certificate_fingerprint}" ]] || fail 'tls-inspection'
  fi
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
  [[ "${expiry_epoch}" =~ ^[0-9]+$ && "${now_epoch}" =~ ^[0-9]+$ ]] || \
    fail 'tls-inspection'
  (( expiry_epoch > now_epoch )) || fail 'tls-inspection'
  validity_days=$(( (expiry_epoch - now_epoch) / 86400 ))
  (( validity_days >= 7 )) || fail 'tls-inspection'
  if [[ -z "${minimum_validity_days}" || validity_days -lt minimum_validity_days ]]; then
    minimum_validity_days=${validity_days}
  fi
done
unset certificate_fingerprint fingerprint fingerprint_line issuer_line hostname_check
printf '[PASS] tls-endpoints=3 hostname-match=true issuer=letsencrypt certificate-consistent=true minimum-validity-days=%s\n' \
  "${minimum_validity_days}"

curl_common=(
  "${curl_bin}"
  --silent
  --show-error
  --noproxy '*'
  --connect-timeout 5
  --max-time 20
  --max-redirs 0
)

curl_status() {
  local resolve_file=$1
  local protocol=$2
  local url=$3
  "${curl_common[@]}" --config "${resolve_file}" --proto "${protocol}" \
    --output /dev/null --write-out '%{http_code}' "${url}" 2>/dev/null
}

argocd_api_capture() {
  local authorization_file=$1
  local url=$2
  "${curl_common[@]}" --fail --config "${curl_resolve_files[0]}" \
    --proto '=https' --header "@${authorization_file}" --output - "${url}" 2>/dev/null
}

require_api_permission() {
  local authorization_file=$1
  local expected=$2
  local action=$3
  local object=$4
  local response value
  case "${object}" in
    '%2A%2F%2A'|'platform%2F%2A'|'platform-bootstrap%2F%2A') ;;
    *) fail 'argocd-rbac' ;;
  esac
  if ! response=$(argocd_api_capture "${authorization_file}" \
    "https://${PHASE5_PUBLIC_HOST}/api/v1/account/can-i/applications/${action}/${object}"); then
    fail 'argocd-rbac'
  fi
  if ! value=$(
    "${python_bin}" -c '
import json, sys
value = json.load(sys.stdin).get("value")
assert value in {"yes", "no"}
print(value)
' <<<"${response}" 2>/dev/null
  ); then
    fail 'argocd-rbac'
  fi
  [[ "${value}" == "${expected}" ]] || fail 'argocd-rbac'
}

for resolve_file in "${curl_resolve_files[@]}"; do
  if ! anonymous_code=$(curl_status "${resolve_file}" '=https' \
    "https://${PHASE5_PUBLIC_HOST}/api/v1/applications"); then
    fail 'argocd-anonymous'
  fi
  [[ "${anonymous_code}" == '401' || "${anonymous_code}" == '403' ]] || \
    fail 'argocd-anonymous'
done
printf '[PASS] argocd-anonymous=denied endpoints=3\n'

admin_token=$(<"${PHASE5_ARGOCD_ADMIN_TOKEN_FILE}")
reviewer_token=$(<"${PHASE5_ARGOCD_REVIEWER_TOKEN_FILE}")
[[ ${#admin_token} -le 16384 && \
   "${admin_token}" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]] || \
  fail 'argocd-auth-file'
[[ ${#reviewer_token} -le 16384 && \
   "${reviewer_token}" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ && \
   "${reviewer_token}" != "${admin_token}" ]] || fail 'argocd-auth-file'

admin_header="${runtime_dir}/admin.authorization.header"
reviewer_header="${runtime_dir}/reviewer.authorization.header"
printf 'Authorization: Bearer %s\n' "${admin_token}" >"${admin_header}"
printf 'Authorization: Bearer %s\n' "${reviewer_token}" >"${reviewer_header}"
chmod 600 "${admin_header}" "${reviewer_header}" || fail 'argocd-auth-file'
unset admin_token reviewer_token

if ! admin_info=$(argocd_api_capture "${admin_header}" \
  "https://${PHASE5_PUBLIC_HOST}/api/v1/session/userinfo"); then
  fail 'argocd-admin-authentication'
fi
if ! reviewer_info=$(argocd_api_capture "${reviewer_header}" \
  "https://${PHASE5_PUBLIC_HOST}/api/v1/session/userinfo"); then
  fail 'argocd-reviewer-authentication'
fi
if ! "${python_bin}" -c '
import json, sys
info = json.load(sys.stdin)
assert info.get("loggedIn") is True
assert info.get("username") == sys.argv[1]
' "${argocd_admin_subject}" <<<"${admin_info}" 2>/dev/null; then
  fail 'argocd-admin-authentication'
fi
if ! "${python_bin}" -c '
import json, sys
info = json.load(sys.stdin)
assert info.get("loggedIn") is True
assert info.get("username") == sys.argv[1]
' "${argocd_reviewer_subject}" <<<"${reviewer_info}" 2>/dev/null; then
  fail 'argocd-reviewer-authentication'
fi

if ! reviewer_apps=$(argocd_api_capture "${reviewer_header}" \
  "https://${PHASE5_PUBLIC_HOST}/api/v1/applications"); then
  fail 'argocd-reviewer-read'
fi
if ! "${python_bin}" -c '
import json, sys
root = sys.argv[1]
expected = {root, *sys.argv[2:]}
items = json.load(sys.stdin).get("items", [])
assert len(items) == len(expected)
assert {item.get("metadata", {}).get("name") for item in items} == expected
' "${argocd_root_app}" "${argocd_child_apps[@]}" <<<"${reviewer_apps}" 2>/dev/null; then
  fail 'argocd-reviewer-read'
fi

require_api_permission "${admin_header}" yes get '%2A%2F%2A'
require_api_permission "${admin_header}" yes sync '%2A%2F%2A'
for reviewer_scope in 'platform%2F%2A' 'platform-bootstrap%2F%2A'; do
  require_api_permission "${reviewer_header}" yes get "${reviewer_scope}"
  require_api_permission "${reviewer_header}" no sync "${reviewer_scope}"
  require_api_permission "${reviewer_header}" no action "${reviewer_scope}"
  require_api_permission "${reviewer_header}" no override "${reviewer_scope}"
done
unset reviewer_scope
unset admin_info reviewer_info reviewer_apps
printf '[PASS] argocd-admin=authenticated reviewer=authenticated reviewer-read=true reviewer-sync=false reviewer-action=false\n'

for resolve_file in "${curl_resolve_files[@]}"; do
  if ! https_code=$(curl_status "${resolve_file}" '=https' \
    "https://${PHASE5_PUBLIC_HOST}/"); then
    fail 'public-https'
  fi
  [[ "${https_code}" == '200' ]] || fail 'public-https'
  if ! http_code=$(curl_status "${resolve_file}" '=http' \
    "http://${PHASE5_PUBLIC_HOST}/"); then
    fail 'public-http'
  fi
  [[ "${http_code}" == '404' ]] || fail 'public-http'
done
printf '[PASS] public-endpoints=3 https=200 http-mode=%s http-status=404\n' \
  "${phase5_http_mode}"

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
