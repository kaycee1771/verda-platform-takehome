#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-apply}"

case "${action}" in
  init|plan|apply)
    ;;
  *)
    echo "usage: $0 [init|plan|apply]" >&2
    exit 64
    ;;
esac

: "${VERDA_CLIENT_ID:?VERDA_CLIENT_ID is required in process memory}"
: "${VERDA_CLIENT_SECRET:?VERDA_CLIENT_SECRET is required in process memory}"
exec pwsh -NoLogo -NoProfile -NonInteractive -File \
  "${repo_root}/scripts/infra/phase2.ps1" -Target "${action}" -Cluster management
