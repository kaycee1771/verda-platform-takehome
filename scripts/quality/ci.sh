#!/usr/bin/env bash
set -Eeuo pipefail

echo '[phase 1] target=ci parity=github-actions network=none credentials=none'
bash scripts/quality/validate.sh
bash scripts/quality/negative-tests.sh
bash scripts/quality/pre-commit.sh
bash scripts/quality/secret-scan.sh
echo '[PASS] CI-equivalent Phase 1 suite completed.'
