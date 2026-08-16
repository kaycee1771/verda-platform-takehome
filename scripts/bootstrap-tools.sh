#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec pwsh -NoLogo -NoProfile -NonInteractive \
  -File "${repo_root}/scripts/quality/bootstrap-tools.ps1"
