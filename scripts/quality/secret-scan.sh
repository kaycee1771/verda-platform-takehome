#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-all}"
report_dir='.local/reports'
mkdir -p "${report_dir}"

echo "[phase 1] target=secret-scan mode=${mode} redaction=100%"
rm -f "${report_dir}/gitleaks-working-tree.json" "${report_dir}/gitleaks-history.json"

gitleaks dir --config .gitleaks.toml --redact=100 --no-banner \
  --report-format json --report-path "${report_dir}/gitleaks-working-tree.json" .
if [[ ! -f "${report_dir}/gitleaks-working-tree.json" ]]; then
  printf '[]\n' >"${report_dir}/gitleaks-working-tree.json"
fi
echo '[PASS] Gitleaks working-tree scan'

if [[ "${mode}" != '--working-tree-only' ]]; then
  if [[ ! -d .git ]]; then
    echo '[FAIL] Whole-history scan requires a full Git working tree.' >&2
    exit 1
  fi
  gitleaks git --config .gitleaks.toml --redact=100 --no-banner \
    --log-opts='--all' --report-format json \
    --report-path "${report_dir}/gitleaks-history.json" .
  if [[ ! -f "${report_dir}/gitleaks-history.json" ]]; then
    printf '[]\n' >"${report_dir}/gitleaks-history.json"
  fi
  echo '[PASS] Gitleaks complete-history scan'
fi
