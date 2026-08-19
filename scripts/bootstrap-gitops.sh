#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/.." && pwd -P)
# shellcheck source=bootstrap/argocd/runtime-lib.sh
source "${repo_root}/bootstrap/argocd/runtime-lib.sh"

runtime_dir=''
port_forward_pid=''
cleanup() {
  if [[ -n "${port_forward_pid}" ]]; then
    kill "${port_forward_pid}" >/dev/null 2>&1 || true
    wait "${port_forward_pid}" 2>/dev/null || true
  fi
  if [[ -n "${runtime_dir}" && -d "${runtime_dir}" ]]; then
    case "${runtime_dir}" in
      "${TMPDIR:-/tmp}"/verda-phase5-gitops.*) rm -rf -- "${runtime_dir}" ;;
      *) phase5_fail 'Refusing to clean an unexpected GitOps temporary path.' ;;
    esac
  fi
}
trap cleanup EXIT

phase5_require_command kubectl
phase5_require_command python3
phase5_require_command realpath
phase5_require_command curl
phase5_require_command openssl
phase5_assert_cluster_runtime "${repo_root}"

root_application="${repo_root}/bootstrap/argocd/root-application.yaml"
phase5_require_regular_file "${root_application}" 'root Application manifest'

root_wait_timeout=${ARGOCD_ROOT_WAIT_TIMEOUT:-15m}
phase5_assert_timeout "${root_wait_timeout}"
case "${root_wait_timeout}" in
  *s) root_wait_seconds=${root_wait_timeout%s} ;;
  *m) root_wait_seconds=$((10#${root_wait_timeout%m} * 60)) ;;
esac

kubectl_base=(
  kubectl
  --kubeconfig "${KUBECONFIG}"
  --context "${PHASE5_KUBE_CONTEXT}"
  --request-timeout=30s
)

"${repo_root}/bootstrap/argocd/install.sh"
"${repo_root}/scripts/wait-for-argocd.sh"

admin_password_path=${ARGOCD_ADMIN_PASSWORD_FILE:-}
[[ -n "${admin_password_path}" ]] || phase5_fail 'ARGOCD_ADMIN_PASSWORD_FILE is required for protected administrator rotation.'
phase5_assert_outside_repo "${repo_root}" "${admin_password_path}" 'ARGOCD_ADMIN_PASSWORD_FILE'
admin_password_parent=$(dirname -- "${admin_password_path}")
[[ -d "${admin_password_parent}" ]] || phase5_fail 'The external administrator-password directory must already exist.'

initial_secret_exists='false'
if "${kubectl_base[@]}" -n argocd get secret argocd-initial-admin-secret >/dev/null 2>&1; then
  initial_secret_exists='true'
fi

if [[ -e "${admin_password_path}" ]]; then
  phase5_require_regular_file "${admin_password_path}" 'ARGOCD_ADMIN_PASSWORD_FILE'
else
  [[ "${initial_secret_exists}" == 'true' ]] ||
    phase5_fail 'The initial credential is absent and no external rotated credential is available.'
  generated_password=$(openssl rand -base64 36 | tr -d '\r\n')
  printf '%s\n' "${generated_password}" >"${admin_password_path}"
  chmod 600 -- "${admin_password_path}"
  unset generated_password
fi

password_mode=$(stat -c '%a' -- "${admin_password_path}")
(( (8#${password_mode} & 077) == 0 )) ||
  phase5_fail 'ARGOCD_ADMIN_PASSWORD_FILE must not be accessible by group or other users.'
IFS= read -r desired_password <"${admin_password_path}"
[[ "${desired_password}" =~ ^[A-Za-z0-9+/=_-]{32,128}$ ]] ||
  phase5_fail 'The external Argo CD administrator credential does not satisfy the protected format contract.'

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/verda-phase5-gitops.XXXXXXXX")
local_port=${ARGOCD_LOCAL_PORT:-18080}
[[ "${local_port}" =~ ^[0-9]+$ ]] || phase5_fail 'ARGOCD_LOCAL_PORT must be numeric.'
(( local_port >= 1024 && local_port <= 65535 )) || phase5_fail 'ARGOCD_LOCAL_PORT is outside the unprivileged TCP range.'

"${kubectl_base[@]}" -n argocd port-forward --address 127.0.0.1 \
  service/argocd-server "${local_port}:443" >"${runtime_dir}/port-forward.log" 2>&1 &
port_forward_pid=$!
for _ in $(seq 1 60); do
  if ! kill -0 "${port_forward_pid}" 2>/dev/null; then
    phase5_fail 'The protected Argo CD port-forward terminated unexpectedly.'
  fi
  if curl --fail --silent --show-error --insecure \
    "https://127.0.0.1:${local_port}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --insecure \
  "https://127.0.0.1:${local_port}/healthz" >/dev/null

create_session() {
  local password=$1
  local response
  response=$(printf '%s' "${password}" | python3 -c '
import json, sys
json.dump({"username": "admin", "password": sys.stdin.read()}, sys.stdout)
' | curl --fail --silent --show-error --insecure \
    --header 'Content-Type: application/json' \
    --data-binary @- \
    "https://127.0.0.1:${local_port}/api/v1/session")
  printf '%s' "${response}" | python3 -c '
import json, sys
token = json.load(sys.stdin).get("token", "")
if len(token) < 32:
    raise SystemExit("Argo CD did not return a valid session token")
sys.stdout.write(token)
'
}

if [[ "${initial_secret_exists}" == 'true' ]]; then
  initial_password=$("${kubectl_base[@]}" -n argocd get secret argocd-initial-admin-secret -o json | python3 -c '
import base64, json, sys
encoded = json.load(sys.stdin).get("data", {}).get("password", "")
password = base64.b64decode(encoded, validate=True).decode("utf-8")
if not password:
    raise SystemExit("the Argo CD initial administrator credential is empty")
sys.stdout.write(password)
')
  session_token=$(create_session "${initial_password}")
  printf 'Authorization: Bearer %s\n' "${session_token}" >"${runtime_dir}/authorization.header"
  printf '%s\0%s' "${initial_password}" "${desired_password}" | python3 -c '
import json, sys
parts = sys.stdin.buffer.read().split(b"\0")
if len(parts) != 2:
    raise SystemExit("invalid protected password payload")
json.dump({
    "name": "admin",
    "currentPassword": parts[0].decode("utf-8"),
    "newPassword": parts[1].decode("utf-8"),
}, sys.stdout)
' | curl --fail --silent --show-error --insecure \
    --request PUT \
    --header 'Content-Type: application/json' \
    --header "@${runtime_dir}/authorization.header" \
    --data-binary @- \
    "https://127.0.0.1:${local_port}/api/v1/account/password" >/dev/null
  unset initial_password session_token
  "${kubectl_base[@]}" -n argocd delete secret argocd-initial-admin-secret \
    --ignore-not-found=true --wait=true >/dev/null
fi

create_session "${desired_password}" >/dev/null
unset desired_password
printf '[PASS] Argo CD initial administrator credential rotated; plaintext retained only in the protected external file.\n'

root_inventory=${ARGOCD_ROOT_INVENTORY_OUTPUT:-${repo_root}/.local/reports/phase5/root-application-inventory.txt}
phase5_assert_report_path "${repo_root}" "${root_inventory}"
mkdir -p -- "$(dirname -- "${root_inventory}")"
python3 - "${root_application}" "${root_inventory}" <<'PY'
import os
from pathlib import Path
import sys
import yaml

manifest, inventory = map(Path, sys.argv[1:])
documents = [item for item in yaml.safe_load_all(manifest.read_text(encoding="utf-8")) if item]
if len(documents) != 1:
    raise SystemExit("the day-zero manifest must contain exactly one object")
app = documents[0]
if app.get("apiVersion") != "argoproj.io/v1alpha1" or app.get("kind") != "Application":
    raise SystemExit("the day-zero object is not an Argo CD Application")
metadata = app.get("metadata", {})
spec = app.get("spec", {})
if metadata.get("name") != "platform-root" or metadata.get("namespace") != "argocd":
    raise SystemExit("the root Application identity is invalid")
if spec.get("project") != "platform-bootstrap":
    raise SystemExit("the root Application does not use the restricted bootstrap project")
source = spec.get("source", {})
if source != {
    "repoURL": "https://github.com/kaycee1771/verda-platform-takehome.git",
    "targetRevision": "main",
    "path": "gitops/root",
}:
    raise SystemExit("the root Application source boundary is invalid")
if spec.get("destination") != {
    "server": "https://kubernetes.default.svc",
    "namespace": "argocd",
}:
    raise SystemExit("the root Application destination boundary is invalid")
automated = spec.get("syncPolicy", {}).get("automated", {})
if automated.get("selfHeal") is not True or automated.get("prune") is not False:
    raise SystemExit("the root Application self-heal/global-prune boundary is invalid")
descriptor = os.open(inventory, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    stream.write("argoproj.io/v1alpha1\tApplication\targocd\tplatform-root\n")
PY

phase5_require_command kubeconform
default_schema_location="${repo_root}/.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json"
schema_location=${ARGOCD_SCHEMA_LOCATION:-${default_schema_location}}
kubeconform -strict -summary -kubernetes-version 1.35.0 \
  -schema-location "${schema_location}" "${root_application}"

"${kubectl_base[@]}" apply \
  --server-side \
  --field-manager=verda-phase5-bootstrap \
  --filename "${root_application}" >/dev/null

deadline=$((SECONDS + root_wait_seconds))
while true; do
  application_json=$("${kubectl_base[@]}" -n argocd get application platform-root -o json)
  if python3 -c '
import json, sys
app = json.load(sys.stdin)
status = app.get("status", {})
operation = status.get("operationState", {}).get("phase", "")
if operation in {"Error", "Failed"}:
    raise SystemExit(2)
if status.get("sync", {}).get("status") != "Synced":
    raise SystemExit(1)
if status.get("health", {}).get("status") != "Healthy":
    raise SystemExit(1)
' <<<"${application_json}" 2>/dev/null; then
    break
  fi
  (( SECONDS < deadline )) || phase5_fail 'The root Application did not become Healthy and Synced before the timeout.'
  sleep 5
done

bootstrap_roots=$("${kubectl_base[@]}" -n argocd get applications \
  -l platform.verda-demo.io/ownership=day-zero -o json | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("items", [])))')
[[ "${bootstrap_roots}" == '1' ]] || phase5_fail 'Exactly one day-zero root Application must exist.'

printf '[PASS] Root Application name=platform-root project=platform-bootstrap status=Healthy/Synced prune=protected.\n'
