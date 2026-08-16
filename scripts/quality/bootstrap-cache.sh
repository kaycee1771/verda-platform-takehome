#!/usr/bin/env bash
set -Eeuo pipefail

echo '[phase 1] target=bootstrap-cache network=bootstrap-only'
mkdir -p .local/terraform-plugin-cache .local/trivy .local/reports .local/logs
export TF_PLUGIN_CACHE_DIR="${PWD}/.local/terraform-plugin-cache"

python scripts/quality/bootstrap_schemas.py

mapfile -t terraform_roots < <(
  find infra/terraform -type f -name '*.tf' -not -path '*/.terraform/*' -printf '%h\n' | sort -u
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

{
  printf 'schema_version=1\n'
  printf 'versions_lock_sha256=%s\n' "$(sha256sum versions.lock.yaml | cut -d' ' -f1)"
  printf 'aqua_config_sha256=%s\n' "$(sha256sum aqua.yaml | cut -d' ' -f1)"
  printf 'schema_lock_sha256=%s\n' "$(sha256sum schemas/schema-sources.lock.yaml | cut -d' ' -f1)"
  printf 'quality_dockerfile_sha256=%s\n' "$(sha256sum tooling/quality/Dockerfile | cut -d' ' -f1)"
  printf 'requirements_quality_sha256=%s\n' "$(sha256sum requirements-quality.txt | cut -d' ' -f1)"
  printf 'bootstrap_tools_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap-tools.ps1 | cut -d' ' -f1)"
  printf 'bootstrap_cache_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap-cache.sh | cut -d' ' -f1)"
  printf 'bootstrap_schemas_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap_schemas.py | cut -d' ' -f1)"
} >.local/bootstrap.complete

echo '[PASS] Offline validation caches prepared.'
