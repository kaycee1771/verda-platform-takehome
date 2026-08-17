#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" != '--confirm' || "${CONFIRM_DESTRUCTIVE_ACTION:-}" != 'yes' ]]; then
  echo 'compute rollback requires --confirm and CONFIRM_DESTRUCTIVE_ACTION=yes' >&2
  exit 64
fi
: "${VERDA_CLIENT_ID:?VERDA_CLIENT_ID is required in process memory}"
: "${VERDA_CLIENT_SECRET:?VERDA_CLIENT_SECRET is required in process memory}"
exec pwsh -NoLogo -NoProfile -NonInteractive -File \
  "${repo_root}/scripts/infra/phase2.ps1" -Target destroy -Cluster management -Confirm
