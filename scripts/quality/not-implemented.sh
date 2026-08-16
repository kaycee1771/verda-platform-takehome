#!/usr/bin/env bash
set -Eeuo pipefail

target="${1:?target is required}"
phase="${2:?required phase is required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "${repo_root}/.local/logs"
message="[phase 1] target=${target} BLOCKED: requires Phase ${phase}. No action was taken."
printf '%s\n' "${message}" | tee "${repo_root}/.local/logs/${target}.log" >&2
exit 64
