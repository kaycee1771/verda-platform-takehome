#!/usr/bin/env bash
set -Eeuo pipefail

# Never permit a caller's xtrace setting to expose password environment values.
set +x
umask 077

readonly PLATFORM_ADMIN_USER="platform-admin"
readonly REVIEWER_USER="verda-reviewer"
readonly FIELD_MANAGER="verda-rancher-account-bootstrap"

usage() {
  cat >&2 <<'EOF'
Usage: register-rancher.sh preflight|reconcile|verify

All modes require:
  KUBECONFIG                         protected direct management kubeconfig
  RANCHER_EXPECTED_HOSTNAME          exact rancher.<IPv4-with-dashes>.sslip.io name
  RANCHER_URL                        https:// plus the exact expected hostname

reconcile additionally requires:
  RANCHER_ACCOUNT_MUTATION_APPROVED  literal yes
  RANCHER_ACCOUNT_MUTATION_SCOPE     literal platform-admin,verda-reviewer
  RANCHER_PLATFORM_ADMIN_PASSWORD    initial password, supplied out of band
  RANCHER_REVIEWER_PASSWORD          different initial password, supplied out of band

No Rancher or Verda API token is accepted. The script uses only the direct kubeconfig and the
Rancher 2.14 management API resources. Existing password Secrets are never overwritten.
EOF
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 64
}

note() {
  printf 'rancher-account-boundary: %s\n' "$1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "required environment variable is unset: ${name}"
}

validate_password() {
  local label="$1"
  local password="$2"
  [[ ${#password} -ge 16 ]] || die "${label} must contain at least 16 characters"
  [[ "$password" != *$'\n'* && "$password" != *$'\r'* ]] || die "${label} must be single-line"
}

kubectl_direct() {
  command kubectl --kubeconfig "${KUBECONFIG}" "$@"
}

validate_direct_boundary() {
  local mode_bits server

  [[ -f "${KUBECONFIG}" ]] || die "direct kubeconfig is not a regular file"
  if command -v stat >/dev/null 2>&1; then
    mode_bits="$(stat -c '%a' "${KUBECONFIG}" 2>/dev/null || true)"
    [[ -z "$mode_bits" || "$mode_bits" == "600" || "$mode_bits" == "400" ]] ||
      die "direct kubeconfig must be mode 0600 or stricter"
  fi

  server="$(kubectl_direct config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
  [[ "$server" == https://* ]] || die "direct kubeconfig server must use HTTPS"
  [[ "$server" != *"${RANCHER_EXPECTED_HOSTNAME}"* ]] ||
    die "break-glass kubeconfig must not depend on the Rancher hostname"
  kubectl_direct get --raw=/readyz >/dev/null
}

anonymous_status() {
  local path="$1"
  command curl \
    --silent \
    --show-error \
    --proto '=https' \
    --tlsv1.2 \
    --connect-timeout 10 \
    --max-time 20 \
    --output /dev/null \
    --write-out '%{http_code}' \
    "${RANCHER_URL}${path}"
}

validate_rancher_boundary() {
  local path status

  [[ "${RANCHER_EXPECTED_HOSTNAME}" =~ ^rancher\.([0-9]{1,3}-){3}[0-9]{1,3}\.sslip\.io$ ]] ||
    die "RANCHER_EXPECTED_HOSTNAME must be an exact rancher sslip.io hostname"
  [[ "${RANCHER_URL}" == "https://${RANCHER_EXPECTED_HOSTNAME}" ]] ||
    die "RANCHER_URL must be HTTPS and exactly match RANCHER_EXPECTED_HOSTNAME"

  status="$(anonymous_status /ping)" || die "Rancher TLS health request failed"
  [[ "$status" == "200" ]] || die "Rancher /ping did not return HTTP 200"

  for path in /v3/clusters /v3/users; do
    status="$(anonymous_status "$path")" || die "anonymous Rancher boundary request failed"
    case "$status" in
      401 | 403) ;;
      *) die "anonymous Rancher management endpoint was not denied" ;;
    esac
  done
}

wait_for_rancher_api() {
  local crd read_only_contract
  for crd in \
    users.management.cattle.io \
    globalrolebindings.management.cattle.io \
    clusterroletemplatebindings.management.cattle.io; do
    kubectl_direct wait --for=condition=Established --timeout=120s "crd/${crd}" >/dev/null
  done

  kubectl_direct -n cattle-system rollout status deployment/rancher --timeout=180s >/dev/null
  kubectl_direct get namespace cattle-local-user-passwords >/dev/null
  kubectl_direct get globalroles.management.cattle.io admin user >/dev/null

  read_only_contract="$(kubectl_direct get roletemplates.management.cattle.io read-only \
    -o jsonpath='{.context}|{.builtin}')"
  [[ "$read_only_contract" == "cluster|true" ]] ||
    die "built-in Rancher read-only role is absent or has an unexpected contract"
}

preflight() {
  validate_direct_boundary
  validate_rancher_boundary
  wait_for_rancher_api
  if kubectl_direct get users.management.cattle.io anonymous >/dev/null 2>&1; then
    die "a Rancher user named anonymous exists"
  fi
}

create_user_if_absent() {
  local username="$1"
  local display_name="$2"
  local password="$3"
  local existing password_b64 hash_annotation attempt

  if kubectl_direct get "users.management.cattle.io/${username}" >/dev/null 2>&1; then
    existing="$(kubectl_direct get "users.management.cattle.io/${username}" \
      -o jsonpath='{.username}|{.displayName}')"
    [[ "$existing" == "${username}|${display_name}" ]] ||
      die "existing Rancher user does not match the protected identity contract: ${username}"
  else
    kubectl_direct create -f - >/dev/null <<EOF
apiVersion: management.cattle.io/v3
kind: User
metadata:
  name: ${username}
displayName: ${display_name}
username: ${username}
enabled: true
mustChangePassword: true
EOF
  fi

  if kubectl_direct -n cattle-local-user-passwords get "secret/${username}" >/dev/null 2>&1; then
    hash_annotation="$(kubectl_direct -n cattle-local-user-passwords get "secret/${username}" \
      -o jsonpath='{.metadata.annotations.cattle\.io/password-hash}')"
    [[ "$hash_annotation" == "pbkdf2sha3512" ]] ||
      die "existing Rancher password Secret is not webhook-hashed: ${username}"
    return
  fi

  password_b64="$(printf '%s' "$password" | base64 | tr -d '\r\n')"
  printf '%s\n' \
    'apiVersion: v1' \
    'kind: Secret' \
    'metadata:' \
    "  name: ${username}" \
    '  namespace: cattle-local-user-passwords' \
    'type: Opaque' \
    'data:' \
    "  password: ${password_b64}" | kubectl_direct create -f - >/dev/null
  unset password_b64 password

  for ((attempt = 1; attempt <= 30; attempt++)); do
    hash_annotation="$(kubectl_direct -n cattle-local-user-passwords get "secret/${username}" \
      -o jsonpath='{.metadata.annotations.cattle\.io/password-hash}' 2>/dev/null || true)"
    [[ "$hash_annotation" == "pbkdf2sha3512" ]] && return
    sleep 1
  done
  die "Rancher webhook did not hash the new password Secret within the bounded wait"
}

apply_role_bindings() {
  kubectl_direct apply --server-side --field-manager="${FIELD_MANAGER}" -f - >/dev/null <<EOF
apiVersion: management.cattle.io/v3
kind: GlobalRoleBinding
metadata:
  name: verda-platform-admin-global-admin
globalRoleName: admin
userName: ${PLATFORM_ADMIN_USER}
---
apiVersion: management.cattle.io/v3
kind: GlobalRoleBinding
metadata:
  name: verda-reviewer-global-user
globalRoleName: user
userName: ${REVIEWER_USER}
---
apiVersion: management.cattle.io/v3
kind: ClusterRoleTemplateBinding
metadata:
  name: verda-reviewer-local-read-only
  namespace: local
clusterName: local
roleTemplateName: read-only
userName: ${REVIEWER_USER}
EOF
}

verify_user_contract() {
  local username="$1"
  local display_name="$2"
  local existing
  existing="$(kubectl_direct get "users.management.cattle.io/${username}" \
    -o jsonpath='{.username}|{.displayName}|{.enabled}')"
  [[ "$existing" == "${username}|${display_name}|true" ]] ||
    die "Rancher user verification failed: ${username}"
}

verify_bindings() {
  local actual
  actual="$(kubectl_direct get globalrolebindings.management.cattle.io/verda-platform-admin-global-admin \
    -o jsonpath='{.globalRoleName}|{.userName}')"
  [[ "$actual" == "admin|${PLATFORM_ADMIN_USER}" ]] || die "platform-admin binding verification failed"

  actual="$(kubectl_direct get globalrolebindings.management.cattle.io/verda-reviewer-global-user \
    -o jsonpath='{.globalRoleName}|{.userName}')"
  [[ "$actual" == "user|${REVIEWER_USER}" ]] || die "reviewer global binding verification failed"

  actual="$(kubectl_direct -n local get \
    clusterroletemplatebindings.management.cattle.io/verda-reviewer-local-read-only \
    -o jsonpath='{.clusterName}|{.roleTemplateName}|{.userName}')"
  [[ "$actual" == "local|read-only|${REVIEWER_USER}" ]] ||
    die "reviewer local read-only binding verification failed"
}

verify_accounts() {
  verify_user_contract "$PLATFORM_ADMIN_USER" "Platform Admin"
  verify_user_contract "$REVIEWER_USER" "Verda Reviewer"
  verify_bindings
}

main() {
  local mode="${1:-}"
  local platform_admin_password=""
  local reviewer_password=""
  [[ $# -eq 1 ]] || {
    usage
    exit 64
  }
  case "$mode" in
    preflight | reconcile | verify) ;;
    *)
      usage
      exit 64
      ;;
  esac

  require_command kubectl
  require_command curl
  require_environment KUBECONFIG
  require_environment RANCHER_EXPECTED_HOSTNAME
  require_environment RANCHER_URL

  if [[ "$mode" == "reconcile" ]]; then
    require_command base64
    require_environment RANCHER_ACCOUNT_MUTATION_APPROVED
    require_environment RANCHER_ACCOUNT_MUTATION_SCOPE
    require_environment RANCHER_PLATFORM_ADMIN_PASSWORD
    require_environment RANCHER_REVIEWER_PASSWORD
    [[ "$RANCHER_ACCOUNT_MUTATION_APPROVED" == "yes" ]] ||
      die "RANCHER_ACCOUNT_MUTATION_APPROVED must equal yes"
    [[ "$RANCHER_ACCOUNT_MUTATION_SCOPE" == "platform-admin,verda-reviewer" ]] ||
      die "RANCHER_ACCOUNT_MUTATION_SCOPE does not match the two authorized identities"
    validate_password RANCHER_PLATFORM_ADMIN_PASSWORD "$RANCHER_PLATFORM_ADMIN_PASSWORD"
    validate_password RANCHER_REVIEWER_PASSWORD "$RANCHER_REVIEWER_PASSWORD"
    [[ "$RANCHER_PLATFORM_ADMIN_PASSWORD" != "$RANCHER_REVIEWER_PASSWORD" ]] ||
      die "platform-admin and reviewer passwords must differ"

    # Copy into non-exported shell locals, then remove the inherited environment
    # values before curl, kubectl, base64, or any other child process starts.
    platform_admin_password="$RANCHER_PLATFORM_ADMIN_PASSWORD"
    reviewer_password="$RANCHER_REVIEWER_PASSWORD"
    unset RANCHER_PLATFORM_ADMIN_PASSWORD RANCHER_REVIEWER_PASSWORD
  fi

  preflight

  case "$mode" in
    preflight)
      note "PASS preflight; direct break-glass and anonymous-deny boundaries are healthy"
      ;;
    reconcile)
      create_user_if_absent "$PLATFORM_ADMIN_USER" "Platform Admin" "$platform_admin_password"
      create_user_if_absent "$REVIEWER_USER" "Verda Reviewer" "$reviewer_password"
      apply_role_bindings
      verify_accounts
      unset platform_admin_password reviewer_password
      note "PASS reconciled two separate local identities; initial passwords require out-of-band change"
      ;;
    verify)
      verify_accounts
      note "PASS account and least-privilege binding contract verified"
      ;;
  esac
}

main "$@"
