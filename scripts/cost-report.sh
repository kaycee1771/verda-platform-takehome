#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${VERDA_CLIENT_ID:?VERDA_CLIENT_ID is required in process memory}"
: "${VERDA_CLIENT_SECRET:?VERDA_CLIENT_SECRET is required in process memory}"
exec pwsh -NoLogo -NoProfile -NonInteractive -File \
  "${repo_root}/scripts/infra/phase2.ps1" -Target cost-report -Cluster management
