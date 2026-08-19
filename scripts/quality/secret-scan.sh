#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-all}"
case "${mode}" in
  all | --working-tree-only) ;;
  *)
    echo "[FAIL] Unsupported secret-scan mode: ${mode}" >&2
    exit 2
    ;;
esac

if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != 'true' ]]; then
  echo '[FAIL] Secret scanning requires a full Git working tree.' >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
report_dir="${repo_root}/.local/reports"
mkdir -p "${report_dir}"

echo "[phase 1] target=secret-scan mode=${mode} redaction=100%"
rm -f "${report_dir}/gitleaks-working-tree.json" "${report_dir}/gitleaks-history.json"

scan_temp="$(mktemp -d -t verda-gitleaks.XXXXXX)"
scan_root="${scan_temp}/worktree"
scan_manifest="${scan_temp}/manifest"
cleanup() {
  rm -rf -- "${scan_temp}"
}
trap cleanup EXIT
mkdir -p "${scan_root}"

# Build a fail-closed mirror of precisely the Git-controlled working surface:
# tracked files plus non-ignored untracked files, with current modifications.
# Downloaded caches and other ignored local state never enter the scan target.
git -C "${repo_root}" ls-files -z --cached --others --exclude-standard >"${scan_manifest}"
while IFS= read -r -d '' path; do
  source_path="${repo_root}/${path}"
  destination_path="${scan_root}/${path}"
  mkdir -p -- "$(dirname -- "${destination_path}")"
  if [[ -L "${source_path}" ]]; then
    cp -P -- "${source_path}" "${destination_path}"
  elif [[ -f "${source_path}" ]]; then
    cp -- "${source_path}" "${destination_path}"
  elif [[ -d "${source_path}" ]]; then
    # A Gitlink records the submodule commit, not the nested working tree.
    continue
  elif git -C "${repo_root}" ls-files --deleted --error-unmatch -- "${path}" >/dev/null 2>&1; then
    # A tracked deletion is absent from the current working-tree surface; its
    # prior content remains covered by the complete-history scan below.
    continue
  else
    printf '[FAIL] Git-controlled path is unreadable: %q\n' "${path}" >&2
    exit 1
  fi
done <"${scan_manifest}"

gitleaks dir --config "${repo_root}/.gitleaks.toml" --redact=100 --no-banner \
  --report-format json --report-path "${report_dir}/gitleaks-working-tree.json" \
  "${scan_root}"
if [[ ! -f "${report_dir}/gitleaks-working-tree.json" ]]; then
  printf '[]\n' >"${report_dir}/gitleaks-working-tree.json"
fi
echo '[PASS] Gitleaks working-tree scan'

if [[ "${mode}" != '--working-tree-only' ]]; then
  gitleaks git --config "${repo_root}/.gitleaks.toml" --redact=100 --no-banner \
    --log-opts='--all' --report-format json \
    --report-path "${report_dir}/gitleaks-history.json" "${repo_root}"
  if [[ ! -f "${report_dir}/gitleaks-history.json" ]]; then
    printf '[]\n' >"${report_dir}/gitleaks-history.json"
  fi
  echo '[PASS] Gitleaks complete-history scan'
fi
