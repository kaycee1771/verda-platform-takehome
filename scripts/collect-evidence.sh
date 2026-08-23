#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
output_dir="${repo_root}/.local/reports"
mkdir -p -- "$output_dir"
output="${output_dir}/platform-verification-$(date -u +%Y%m%dT%H%M%SZ).txt"

{
  printf 'collected_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 "${repo_root}/scripts/status.py"
  bash "${repo_root}/scripts/verify-platform.sh"
} | tee "$output"
chmod 600 "$output"
printf 'private_report=%s\n' "$output"
