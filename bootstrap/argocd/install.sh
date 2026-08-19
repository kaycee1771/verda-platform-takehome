#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/../.." && pwd -P)
# shellcheck source=bootstrap/argocd/runtime-lib.sh
source "${script_dir}/runtime-lib.sh"

readonly release_name='argocd'
readonly namespace='argocd'
readonly chart_version='10.3.3'
readonly app_version='v3.5.1'
readonly chart_archive_name="argo-cd-${chart_version}.tgz"
readonly chart_url="https://github.com/argoproj/argo-helm/releases/download/argo-cd-${chart_version}/${chart_archive_name}"
readonly checksum_file="${script_dir}/${chart_archive_name}.sha256"
readonly values_file="${script_dir}/values.yaml"

runtime_dir=''
cleanup() {
  if [[ -n "${runtime_dir}" && -d "${runtime_dir}" ]]; then
    case "${runtime_dir}" in
      "${TMPDIR:-/tmp}"/verda-phase5-argocd.*) rm -rf -- "${runtime_dir}" ;;
      *) phase5_fail 'Refusing to clean an unexpected Argo CD temporary path.' ;;
    esac
  fi
}
trap cleanup EXIT

usage() {
  cat >&2 <<'EOF'
Usage:
  bootstrap/argocd/install.sh
  bootstrap/argocd/install.sh --rollback <helm-revision>

Required environment:
  KUBECONFIG                 Explicit external kubeconfig file.
  PHASE5_KUBE_CONTEXT        Exact current kubeconfig context.
  PHASE5_CONFIRM_CLUSTER     Must equal verda-mgmt.

Optional environment:
  ARGOCD_CHART_ARCHIVE       Offline chart cache; its checksum is always verified.
  ARGOCD_HELM_TIMEOUT        Helm timeout (default: 15m).
  ARGOCD_INVENTORY_OUTPUT    Sanitized inventory under .local/reports/phase5/.
EOF
  exit 64
}

mode='install'
rollback_revision=''
case "$#" in
  0) ;;
  2)
    [[ "$1" == '--rollback' ]] || usage
    mode='rollback'
    rollback_revision=$2
    [[ "${rollback_revision}" =~ ^[1-9][0-9]*$ ]] || phase5_fail 'The Helm rollback revision must be a positive integer.'
    ;;
  *) usage ;;
esac

phase5_require_command helm
phase5_require_command kubectl
phase5_require_command python3
phase5_require_command realpath
phase5_assert_cluster_runtime "${repo_root}"

helm_timeout=${ARGOCD_HELM_TIMEOUT:-15m}
phase5_assert_timeout "${helm_timeout}"

helm_base=(
  helm
  --kubeconfig "${KUBECONFIG}"
  --kube-context "${PHASE5_KUBE_CONTEXT}"
)
kubectl_base=(
  kubectl
  --kubeconfig "${KUBECONFIG}"
  --context "${PHASE5_KUBE_CONTEXT}"
  --request-timeout=30s
)

if [[ "${mode}" == 'rollback' ]]; then
  expected_confirmation="argocd:${rollback_revision}"
  [[ ${ARGOCD_CONFIRM_ROLLBACK:-} == "${expected_confirmation}" ]] ||
    phase5_fail "Set ARGOCD_CONFIRM_ROLLBACK=${expected_confirmation} to authorize only this rollback."
  history_json=$("${helm_base[@]}" history "${release_name}" --namespace "${namespace}" --output json)
  python3 -c '
import json, sys
revision, version = sys.argv[1:]
history = json.load(sys.stdin)
matches = [item for item in history if str(item.get("revision")) == revision]
if len(matches) != 1:
    raise SystemExit("requested Helm rollback revision is absent")
if matches[0].get("chart") != f"argo-cd-{version}":
    raise SystemExit("requested rollback revision does not use the pinned Argo CD chart")
' "${rollback_revision}" "${chart_version}" <<<"${history_json}"
  "${helm_base[@]}" rollback "${release_name}" "${rollback_revision}" \
    --namespace "${namespace}" \
    --wait \
    --wait-for-jobs \
    --cleanup-on-fail \
    --timeout "${helm_timeout}"
  printf '[PASS] Argo CD Helm release rolled back to verified revision %s.\n' "${rollback_revision}"
  exit 0
fi

if "${kubectl_base[@]}" get namespace "${namespace}" >/dev/null 2>&1; then
  namespace_phase=$("${kubectl_base[@]}" get namespace "${namespace}" -o jsonpath='{.status.phase}')
  [[ "${namespace_phase}" == 'Active' ]] || phase5_fail 'The existing argocd namespace is not Active.'
  release_json=$("${helm_base[@]}" list --namespace "${namespace}" --filter '^argocd$' --output json)
  python3 -c '
import json, sys
chart_version, app_version = sys.argv[1:]
releases = json.load(sys.stdin)
if len(releases) != 1:
    raise SystemExit("the existing argocd namespace is not owned by exactly one argocd Helm release")
release = releases[0]
if release.get("chart") != f"argo-cd-{chart_version}":
    raise SystemExit("the existing Argo CD release does not use the pinned chart")
if release.get("app_version") != app_version:
    raise SystemExit("the existing Argo CD release does not use the pinned application version")
' "${chart_version}" "${app_version}" <<<"${release_json}"
else
  release_json=$("${helm_base[@]}" list --all-namespaces --filter '^argocd$' --output json)
  python3 -c '
import json, sys
if json.load(sys.stdin):
    raise SystemExit("an argocd Helm release exists outside the intended namespace")
' <<<"${release_json}"
fi

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/verda-phase5-argocd.XXXXXXXX")
archive="${runtime_dir}/${chart_archive_name}"

if [[ -n ${ARGOCD_CHART_ARCHIVE:-} ]]; then
  phase5_require_regular_file "${ARGOCD_CHART_ARCHIVE}" 'ARGOCD_CHART_ARCHIVE'
  cp -- "${ARGOCD_CHART_ARCHIVE}" "${archive}"
  acquisition='verified-offline-cache'
else
  phase5_require_command curl
  curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --proto '=https' \
    --tlsv1.2 \
    --retry 3 \
    --retry-all-errors \
    --output "${archive}" \
    "${chart_url}"
  acquisition='verified-official-release'
fi

phase5_require_command sha256sum
(
  cd -- "${runtime_dir}"
  sha256sum --check --strict "${checksum_file}"
) >/dev/null

chart_metadata=$("${helm_base[@]}" show chart "${archive}")
python3 -c '
import sys, yaml
expected_chart, expected_app = sys.argv[1:]
metadata = yaml.safe_load(sys.stdin)
if metadata.get("name") != "argo-cd":
    raise SystemExit("the checksummed archive is not the Argo CD chart")
if str(metadata.get("version")) != expected_chart:
    raise SystemExit("the checksummed archive has an unexpected chart version")
if str(metadata.get("appVersion")) != expected_app:
    raise SystemExit("the checksummed archive has an unexpected application version")
' "${chart_version}" "${app_version}" <<<"${chart_metadata}"

rendered="${runtime_dir}/argocd-rendered.yaml"
"${helm_base[@]}" lint "${archive}" --strict --values "${values_file}"
"${helm_base[@]}" template "${release_name}" "${archive}" \
  --namespace "${namespace}" \
  --include-crds \
  --values "${values_file}" >"${rendered}"

inventory_output=${ARGOCD_INVENTORY_OUTPUT:-${repo_root}/.local/reports/phase5/argocd-bootstrap-inventory.txt}
phase5_assert_report_path "${repo_root}" "${inventory_output}"
mkdir -p -- "$(dirname -- "${inventory_output}")"
python3 "${script_dir}/validate-render.py" \
  --manifest "${rendered}" \
  --inventory "${inventory_output}"

phase5_require_command kubeconform
default_schema_location="${repo_root}/.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json"
schema_location=${ARGOCD_SCHEMA_LOCATION:-${default_schema_location}}
kubeconform \
  -strict \
  -summary \
  -skip CustomResourceDefinition \
  -kubernetes-version 1.35.0 \
  -schema-location "${schema_location}" \
  "${rendered}"

"${helm_base[@]}" upgrade --install "${release_name}" "${archive}" \
  --namespace "${namespace}" \
  --create-namespace \
  --values "${values_file}" \
  --atomic \
  --wait \
  --wait-for-jobs \
  --timeout "${helm_timeout}" \
  --history-max 5

printf '[PASS] Argo CD chart=%s app=%s source=%s checksum=verified namespace=%s.\n' \
  "${chart_version}" "${app_version}" "${acquisition}" "${namespace}"
