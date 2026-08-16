#!/usr/bin/env bash
set -Eeuo pipefail

root='.local/negative-quality-gates'
reports='.local/reports/negative'

cleanup() {
  rm -rf -- "${root}"
}
trap cleanup EXIT
cleanup
mkdir -p "${root}" "${reports}"

echo '[phase 1] target=validate-negative fixture-policy=generated-and-ignored'

expect_rejected() {
  local name="$1"
  shift
  local log="${reports}/${name}.log"
  if "$@" >"${log}" 2>&1; then
    echo "[FAIL] ${name}: invalid input was accepted" >&2
    return 1
  fi
  echo "[PASS] ${name}: invalid input rejected"
}

printf '%s\n' 'resource "terraform_data" "broken" {' '  input = {' >"${root}/malformed.tf"
expect_rejected malformed-terraform terraform fmt -check "${root}/malformed.tf"

printf '%s\n' \
  '---' \
  'apiVersion: v1' \
  'kind: ConfigMap' \
  'metadata:' \
  '  name: invalid-schema-fixture' \
  'data: []' >"${root}/invalid-configmap.yaml"
expect_rejected invalid-kubernetes-object kubeconform \
  -strict -kubernetes-version 1.35.0 \
  -schema-location '.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json' \
  "${root}/invalid-configmap.yaml"

printf '%s\n' \
  '---' \
  'apiVersion: untrusted.example.io/v1' \
  'kind: UnknownCustomResource' \
  'metadata:' \
  '  name: missing-schema-fixture' >"${root}/missing-custom-schema.yaml"
expect_rejected missing-custom-schema kubeconform \
  -strict -kubernetes-version 1.35.0 \
  -schema-location '.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json' \
  "${root}/missing-custom-schema.yaml"

printf '%s\n' \
  '---' \
  'groups:' \
  '  - name: deliberately-invalid' \
  '    rules:' \
  '      - alert: BrokenExpression' \
  '        expr: rate(http_requests_total[5m]' >"${root}/invalid-alert.yaml"
expect_rejected invalid-alert-rule promtool check rules "${root}/invalid-alert.yaml"

ssh-keygen -q -t ed25519 -N '' -C 'phase-1-generated-negative-fixture' \
  -f "${root}/generated-test-key"
expect_rejected generated-private-key gitleaks dir --config .gitleaks.toml \
  --redact=100 --no-banner "${root}"

mkdir -p "${root}/action-pins/workflows"
printf '%s\n' \
  '---' \
  'schema_version: 2' \
  'ci_actions:' \
  '  checkout:' \
  '    uses: "actions/checkout"' \
  '    release: "v6"' \
  '    sha: "0000000000000000000000000000000000000000"' \
  >"${root}/action-pins/versions.lock.yaml"
printf '%s\n' \
  '---' \
  'name: Invalid action pin fixture' \
  'on: workflow_dispatch' \
  'jobs:' \
  '  validate:' \
  '    runs-on: ubuntu-24.04' \
  '    steps:' \
  '      - uses: actions/checkout@1111111111111111111111111111111111111111' \
  >"${root}/action-pins/workflows/invalid.yml"
expect_rejected mismatched-github-action-pin python scripts/quality/check_action_pins.py \
  --lock "${root}/action-pins/versions.lock.yaml" \
  --workflows "${root}/action-pins/workflows"

printf '%s\n' \
  'malformed_terraform=REJECTED' \
  'invalid_kubernetes_object=REJECTED' \
  'missing_custom_schema=REJECTED' \
  'invalid_alert_rule=REJECTED' \
  'generated_private_key=REJECTED' \
  'mismatched_github_action_pin=REJECTED' >"${reports}/summary.txt"

echo '[PASS] Every Phase 1 negative quality gate rejected its invalid input.'
