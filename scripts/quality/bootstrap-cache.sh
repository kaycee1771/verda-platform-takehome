#!/usr/bin/env bash
set -Eeuo pipefail

echo '[phase 1] target=bootstrap-cache network=bootstrap-only'
mkdir -p .local/terraform-plugin-cache .local/trivy .local/reports .local/logs
export TF_PLUGIN_CACHE_DIR="${PWD}/.local/terraform-plugin-cache"

python scripts/quality/bootstrap_schemas.py
python scripts/quality/bootstrap_charts.py

mapfile -t terraform_roots < <(
  find infra/terraform -type f -name '.terraform-root' -printf '%h\n' | sort -u
)
if ((${#terraform_roots[@]} == 0)); then
  echo '[N/A] Terraform provider cache: no root modules exist.'
else
  for root in "${terraform_roots[@]}"; do
    echo "[BOOTSTRAP] terraform init root=${root}"
    terraform -chdir="${root}" init -backend=false -input=false -lockfile=readonly
  done
fi

if [[ -f .local/trivy/policy/metadata.json ]]; then
  echo '[BOOTSTRAP] Trivy misconfiguration policy cache already present; immutable cache retained.'
else
  echo '[BOOTSTRAP] Trivy misconfiguration policy cache'
  trivy config --cache-dir .local/trivy --exit-code 0 --quiet \
    --skip-dirs .git --skip-dirs .local --skip-dirs tmp . >/dev/null
fi

bash scripts/quality/write-cache-marker.sh

echo '[PASS] Offline validation caches prepared.'
