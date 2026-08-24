#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

readonly REVIEWER_ID='u-924mt'
die() { printf 'ERROR: %s\n' "$1" >&2; exit 64; }
note() { printf 'rancher-account-boundary: %s\n' "$1"; }
require() { command -v "$1" >/dev/null 2>&1 || die "required command unavailable: $1"; }
kubectl_direct() { command kubectl --kubeconfig "$KUBECONFIG" "$@"; }

protected_file() {
  local path="$1" mode
  [[ "$path" == /* && -f "$path" && ! -L "$path" ]] || die 'protected input must be a regular absolute file'
  mode="$(stat -c '%a' -- "$path")"
  [[ "$mode" == 600 || "$mode" == 400 ]] || die 'protected input must be mode 0600 or stricter'
}

preflight() {
  local server status
  protected_file "$KUBECONFIG"
  server="$(kubectl_direct config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
  [[ "$server" == https://* && "$server" != *"$RANCHER_EXPECTED_HOSTNAME"* ]] || die 'direct kubeconfig boundary is invalid'
  kubectl_direct get --raw=/readyz >/dev/null
  kubectl_direct -n cattle-system rollout status deployment/rancher --timeout=180s >/dev/null
  status="$(curl --silent --show-error --proto '=https' --tlsv1.2 --max-time 20 --output /dev/null --write-out '%{http_code}' "$RANCHER_URL/ping")"
  [[ "$status" == 200 ]] || die 'Rancher health check failed'
}

verify_login_and_authorization() {
  local runtime login_body login_response auth_header resource output
  protected_file "$RANCHER_REVIEWER_CREDENTIAL_FILE"
  runtime="$(mktemp -d "${TMPDIR:-/tmp}/verda-rancher-verify.XXXXXX")"
  chmod 700 "$runtime"
  trap 'rm -rf -- "$runtime"' EXIT
  login_body="$runtime/login.json"; login_response="$runtime/response.json"; auth_header="$runtime/authorization"
  python3 - "$RANCHER_REVIEWER_CREDENTIAL_FILE" "$login_body" <<'PY'
import json, pathlib, re, sys
rows = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
assert len(rows) == 2 and rows[0] == 'verda-evaluator-final-20260824'
assert 16 <= len(rows[1]) <= 256 and not any(c.isspace() for c in rows[1])
pathlib.Path(sys.argv[2]).write_text(json.dumps({'type':'localProvider','username':rows[0],
    'password':rows[1],'responseType':'json','description':'Rancher evaluator verification'},
    separators=(',', ':')), encoding='utf-8')
PY
  chmod 600 "$login_body"
  curl --silent --show-error --fail --proto '=https' --tlsv1.2 --max-time 30 --header 'Content-Type: application/json' --data-binary "@$login_body" --output "$login_response" "$RANCHER_URL/v1-public/login"
  python3 - "$login_response" "$auth_header" <<'PY'
import json, pathlib, re, sys
token = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')).get('token', '')
assert re.fullmatch(r'[A-Za-z0-9._~+/=:-]{24,16384}', token)
pathlib.Path(sys.argv[2]).write_text('Authorization: Bearer ' + token + '\n', encoding='utf-8')
PY
  chmod 600 "$login_response" "$auth_header"
  for resource in management.cattle.io.nodes namespaces apps.deployments secrets; do
    output="$runtime/${resource//./-}.json"
    curl --silent --show-error --fail --proto '=https' --tlsv1.2 --max-time 30 --header "@$auth_header" --output "$output" "$RANCHER_URL/v1/$resource"
    chmod 600 "$output"
  done
  python3 - "$runtime" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
def data(name): return json.loads((root / name).read_text(encoding='utf-8')).get('data', [])
assert len(data('management-cattle-io-nodes.json')) == 3
assert {x.get('metadata', {}).get('name') for x in data('namespaces.json')} == {'demo-dev','demo-staging','demo-prod'}
assert {x.get('metadata', {}).get('namespace') for x in data('apps-deployments.json')} == {'demo-dev','demo-staging','demo-prod'}
assert not data('secrets.json')
PY
  for namespace in demo-dev demo-staging demo-prod; do
    [[ "$(kubectl_direct auth can-i get deployments -n "$namespace" --as="$REVIEWER_ID")" == yes ]] || die 'reviewer workload read denied'
  done
  for verb in create update patch delete; do
    [[ "$(kubectl_direct auth can-i "$verb" deployments -n demo-dev --as="$REVIEWER_ID")" == no ]] || die 'reviewer mutation unexpectedly allowed'
  done
  [[ "$(kubectl_direct auth can-i get secrets -n demo-dev --as="$REVIEWER_ID")" == no ]] || die 'reviewer Secret access unexpectedly allowed'
  [[ "$(kubectl_direct auth can-i create pods/exec -n demo-dev --as="$REVIEWER_ID")" == no ]] || die 'reviewer exec unexpectedly allowed'
  [[ "$(kubectl_direct auth can-i impersonate users --as="$REVIEWER_ID")" == no ]] || die 'reviewer impersonation unexpectedly allowed'
}

main() {
  local mode="${1:-}"
  [[ $# -eq 1 && "$mode" =~ ^(preflight|verify)$ ]] || die 'usage: register-rancher.sh preflight|verify'
  for binary in kubectl curl python3 stat mktemp chmod rm; do require "$binary"; done
  [[ -n "${KUBECONFIG:-}" && -n "${RANCHER_EXPECTED_HOSTNAME:-}" && -n "${RANCHER_URL:-}" ]] ||
    die 'required Rancher boundary environment is missing'
  [[ "$RANCHER_EXPECTED_HOSTNAME" =~ ^rancher\.([0-9]{1,3}-){3}[0-9]{1,3}\.nip\.io$ ]] || die 'invalid Rancher hostname'
  [[ "$RANCHER_URL" == "https://$RANCHER_EXPECTED_HOSTNAME" ]] || die 'invalid Rancher URL'
  preflight
  if [[ "$mode" == verify ]]; then
    [[ -n "${RANCHER_REVIEWER_CREDENTIAL_FILE:-}" ]] || die 'reviewer credential file is missing'
    verify_login_and_authorization
    note 'PASS evaluator login, read visibility and mutation denial verified'
  else
    note 'PASS preflight; direct recovery and Rancher health boundaries verified'
  fi
}
main "$@"
