#!/usr/bin/env bash
set -Eeuo pipefail

mkdir -p .local

{
  printf 'schema_version=2\n'
  printf 'toolchain_lock_sha256=%s\n' "$(python scripts/quality/cache_fingerprint.py versions.lock.yaml)"
  printf 'aqua_config_sha256=%s\n' "$(sha256sum aqua.yaml | cut -d' ' -f1)"
  printf 'schema_lock_sha256=%s\n' "$(sha256sum schemas/schema-sources.lock.yaml | cut -d' ' -f1)"
  printf 'quality_dockerfile_sha256=%s\n' "$(sha256sum tooling/quality/Dockerfile | cut -d' ' -f1)"
  printf 'requirements_quality_sha256=%s\n' "$(sha256sum requirements-quality.txt | cut -d' ' -f1)"
  printf 'bootstrap_tools_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap-tools.ps1 | cut -d' ' -f1)"
  printf 'bootstrap_cache_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap-cache.sh | cut -d' ' -f1)"
  printf 'bootstrap_schemas_sha256=%s\n' "$(sha256sum scripts/quality/bootstrap_schemas.py | cut -d' ' -f1)"
  printf 'cache_fingerprint_sha256=%s\n' "$(sha256sum scripts/quality/cache_fingerprint.py | cut -d' ' -f1)"
  printf 'write_cache_marker_sha256=%s\n' "$(sha256sum scripts/quality/write-cache-marker.sh | cut -d' ' -f1)"
} >.local/bootstrap.complete

echo '[PASS] Offline cache marker records cache-affecting inputs only.'
