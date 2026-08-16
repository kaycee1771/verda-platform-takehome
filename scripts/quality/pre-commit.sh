#!/usr/bin/env bash
set -Eeuo pipefail

echo '[phase 1] target=pre-commit scope=all-tracked-files'
pre-commit run --all-files --show-diff-on-failure
echo '[PASS] All configured pre-commit hooks passed.'
