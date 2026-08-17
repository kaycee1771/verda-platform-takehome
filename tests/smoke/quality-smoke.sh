#!/usr/bin/env bash
set -Eeuo pipefail

test -f .local/bootstrap.complete
test -f .local/schema-cache/configmap-v1.json
kubeconform -strict -kubernetes-version 1.35.0 \
  -schema-location '.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json' \
  tests/fixtures/kubernetes/valid

phase_gate_log='/tmp/verda-phase-2-credential-gate.log'
if bash scripts/provision.sh >"${phase_gate_log}" 2>&1; then
  echo '[FAIL] Phase 2 provision wrapper unexpectedly succeeded without credentials.' >&2
  exit 1
fi
grep -q 'VERDA_CLIENT_ID is required in process memory' "${phase_gate_log}"
printf '%s\n' '[PASS] Phase 1 shell smoke harness'
