#!/usr/bin/env bash

phase5_fail() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

phase5_require_command() {
  command -v "$1" >/dev/null 2>&1 || phase5_fail "Required command '$1' is unavailable."
}

phase5_require_regular_file() {
  local path=$1
  local label=$2
  [[ -f "${path}" && ! -L "${path}" ]] || phase5_fail "${label} must name a regular, non-symlink file."
}

phase5_assert_timeout() {
  [[ "$1" =~ ^[1-9][0-9]*(s|m)$ ]] || phase5_fail 'Timeouts must be positive whole seconds or minutes.'
}

phase5_assert_outside_repo() {
  local repo_root=$1
  local candidate=$2
  local label=$3
  local repo_real candidate_real
  repo_real=$(realpath -m -- "${repo_root}")
  candidate_real=$(realpath -m -- "${candidate}")
  case "${candidate_real}" in
    "${repo_real}"|"${repo_real}"/*) phase5_fail "${label} must remain outside the repository." ;;
  esac
}

phase5_assert_report_path() {
  local repo_root=$1
  local candidate=$2
  local allowed candidate_real
  allowed=$(realpath -m -- "${repo_root}/.local/reports/phase5")
  candidate_real=$(realpath -m -- "${candidate}")
  case "${candidate_real}" in
    "${allowed}"/*) ;;
    *) phase5_fail 'Sanitized runtime inventory must remain under .local/reports/phase5.' ;;
  esac
}

phase5_assert_cluster_runtime() {
  local repo_root=$1
  local current_context api_server nodes_json

  [[ -n ${KUBECONFIG:-} ]] || phase5_fail 'KUBECONFIG is required; ambient Kubernetes configuration is forbidden.'
  phase5_require_regular_file "${KUBECONFIG}" 'KUBECONFIG'
  phase5_assert_outside_repo "${repo_root}" "${KUBECONFIG}" 'KUBECONFIG'
  [[ -n ${PHASE5_KUBE_CONTEXT:-} ]] || phase5_fail 'PHASE5_KUBE_CONTEXT is required.'
  [[ ${PHASE5_CONFIRM_CLUSTER:-} == 'verda-mgmt' ]] ||
    phase5_fail 'PHASE5_CONFIRM_CLUSTER must equal verda-mgmt.'

  current_context=$(kubectl --kubeconfig "${KUBECONFIG}" config current-context)
  [[ "${current_context}" == "${PHASE5_KUBE_CONTEXT}" ]] ||
    phase5_fail 'The kubeconfig current context does not match PHASE5_KUBE_CONTEXT.'
  [[ $(kubectl --kubeconfig "${KUBECONFIG}" config get-contexts "${PHASE5_KUBE_CONTEXT}" -o name) == "${PHASE5_KUBE_CONTEXT}" ]] ||
    phase5_fail 'The required kubeconfig context is absent or ambiguous.'

  api_server=$(kubectl --kubeconfig "${KUBECONFIG}" --context "${PHASE5_KUBE_CONTEXT}" \
    config view --minify -o jsonpath='{.clusters[0].cluster.server}')
  [[ "${api_server}" == https://* ]] || phase5_fail 'The selected Kubernetes context does not use a TLS API endpoint.'

  nodes_json=$(kubectl --kubeconfig "${KUBECONFIG}" --context "${PHASE5_KUBE_CONTEXT}" \
    --request-timeout=30s get nodes -o json)
  python3 -c '
import json, sys
expected = {"verda-mgmt-server-01", "verda-mgmt-server-02", "verda-mgmt-server-03"}
nodes = json.load(sys.stdin).get("items", [])
names = {node.get("metadata", {}).get("name") for node in nodes}
if names != expected or len(nodes) != 3:
    raise SystemExit("the selected cluster does not have the exact management-node identity")
for node in nodes:
    conditions = {c.get("type"): c.get("status") for c in node.get("status", {}).get("conditions", [])}
    if conditions.get("Ready") != "True":
        raise SystemExit("a management node is not Ready")
    if node.get("spec", {}).get("unschedulable", False):
        raise SystemExit("a management node is unexpectedly unschedulable")
' <<<"${nodes_json}"
}
