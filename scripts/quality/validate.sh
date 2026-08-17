#!/usr/bin/env bash
set -Eeuo pipefail

failures=()
render_dir='.local/rendered'
schema_location='.local/schema-cache/{{.ResourceKind}}{{.KindSuffix}}.json'
mkdir -p "${render_dir}" .local/reports

echo '[phase 1] target=validate network=none cloud-credentials=not-mounted'

run_gate() {
  local name="$1"
  shift
  echo "[RUN] ${name}"
  if "$@"; then
    echo "[PASS] ${name}"
  else
    local status=$?
    echo "[FAIL] ${name} (exit=${status})" >&2
    failures+=("${name}")
  fi
}

not_applicable() {
  printf '[N/A] %s: %s\n' "$1" "$2"
}

terraform_validate() {
  local root
  mapfile -t roots < <(
    find infra/terraform -type f -name '.terraform-root' -printf '%h\n' | sort -u
  )
  for root in "${roots[@]}"; do
    [[ -d "${root}/.terraform" ]] || {
      echo "${root}: provider cache is absent; run 'make bootstrap-tools'" >&2
      return 1
    }
    terraform -chdir="${root}" validate
  done
}

terraform_test() {
  local root
  mapfile -t roots < <(
    find infra/terraform -type f -name '.terraform-root' -printf '%h\n' | sort -u
  )
  for root in "${roots[@]}"; do
    if find "${root}" -type f \( -name '*.tftest.hcl' -o -name '*.tftest.json' \) -print -quit | grep -q .; then
      terraform -chdir="${root}" test -no-color
    fi
  done
}

tflint_validate() {
  local root
  mapfile -t roots < <(
    find infra/terraform -type f -name '*.tf' -not -path '*/.terraform/*' -printf '%h\n' | sort -u
  )
  for root in "${roots[@]}"; do
    tflint --chdir="${root}" --config="${PWD}/.tflint.hcl"
  done
}

ansible_validate() {
  ANSIBLE_CONFIG=infra/ansible/ansible.cfg ansible-lint --offline infra/ansible
}

shell_validate() {
  mapfile -d '' shell_files < <(
    find scripts bootstrap tests -type f -name '*.sh' -print0
  )
  shellcheck --external-sources "${shell_files[@]}"
}

helm_validate() {
  local chart
  mapfile -t charts < <(find tests/fixtures/helm -name Chart.yaml -printf '%h\n' | sort -u)
  for chart in "${charts[@]}"; do
    helm lint "${chart}" --strict
    helm template phase1-fixture "${chart}" \
      --namespace quality-system >"${render_dir}/$(basename "${chart}").yaml"
  done
}

kubernetes_validate() {
  kubeconform -strict -summary -kubernetes-version 1.35.0 \
    -schema-location "${schema_location}" \
    tests/fixtures/kubernetes/valid \
    policies/kyverno/tests/policy.yaml \
    policies/kyverno/tests/resources.yaml \
    "${render_dir}"
}

prometheus_validate() {
  local rule_file
  mapfile -t rule_files < <(find observability/rules -maxdepth 1 -type f -name '*.yaml' ! -name 'tests.yaml' | sort)
  for rule_file in "${rule_files[@]}"; do
    promtool check rules "${rule_file}"
  done
  (cd observability/rules && promtool test rules tests.yaml)
}

trivy_validate() {
  trivy config --cache-dir .local/trivy --skip-check-update --timeout 15m --exit-code 1 \
    --severity HIGH,CRITICAL \
    --skip-dirs .git --skip-dirs .local --skip-dirs tmp \
    --skip-dirs tests --skip-dirs policies/kyverno/tests \
    --skip-dirs '**/.terraform' .
}

go_format_validate() {
  local unformatted
  unformatted="$(gofmt -l applications/platform-demo)"
  if [[ -n "${unformatted}" ]]; then
    printf '%s\n' "${unformatted}"
    return 1
  fi
}

dockerfile_validate() {
  mapfile -d '' dockerfiles < <(find . -type f -name Dockerfile -not -path './.git/*' -not -path './.local/*' -print0)
  hadolint --config .hadolint.yaml "${dockerfiles[@]}"
}

markdown_validate() {
  mapfile -d '' markdown_files < <(
    find . -type f -name '*.md' -not -path './.git/*' -not -path './.local/*' \
      -not -path './tmp/*' -not -name 'VERDA_PLATFORM_TAKEHOME_MASTER_BLUEPRINT.md' -print0
  )
  pymarkdown --config .pymarkdown.json scan "${markdown_files[@]}"
}

run_gate 'repository structure contract' python scripts/quality/check_structure.py
run_gate 'exact tool version lock' python scripts/quality/check_versions.py
run_gate 'Terraform format' terraform fmt -check -recursive infra/terraform
run_gate 'Phase 2 plan assertion unit tests' \
  python -m unittest discover -s tests/static -p 'test_*.py'

mapfile -t tf_roots < <(find infra/terraform -type f -name '.terraform-root' -printf '%h\n' | sort -u)
if ((${#tf_roots[@]})); then
  run_gate 'Terraform validate (all roots)' terraform_validate
  run_gate 'TFLint (all roots)' tflint_validate
  run_gate 'Terraform native contract tests' terraform_test
else
  not_applicable 'Terraform validate/TFLint' 'no Terraform root modules exist'
fi

run_gate 'Trivy canonical IaC misconfiguration scan' trivy_validate

if find infra/ansible -type f \( -name '*.yml' -o -name '*.yaml' \) -print -quit | grep -q .; then
  run_gate 'Ansible lint' ansible_validate
else
  not_applicable 'Ansible lint' 'no Ansible YAML exists'
fi

run_gate 'YAML lint' yamllint --config-file .yamllint.yaml .

if find scripts bootstrap tests -type f -name '*.sh' -print -quit | grep -q .; then
  run_gate 'ShellCheck' shell_validate
  run_gate 'Shell smoke harness' bash tests/smoke/quality-smoke.sh
else
  not_applicable 'ShellCheck/smoke harness' 'no shell scripts exist'
fi

if find tests/fixtures/helm -name Chart.yaml -print -quit | grep -q .; then
  run_gate 'Helm lint and fixture render' helm_validate
else
  not_applicable 'Helm lint' 'no chart exists'
fi
not_applicable 'application environment Helm renders' 'application chart begins in Phase 6; the Phase 1 chart fixture is validated above'
run_gate 'Kubernetes and CRD schema validation' kubernetes_validate
run_gate 'Kyverno passing/failing policy fixtures' kyverno test policies/kyverno/tests --detailed-results
run_gate 'Prometheus rule syntax and unit tests' prometheus_validate

if find . -type f -name '*.go' -not -path './.git/*' -not -path './.local/*' -print -quit | grep -q .; then
  run_gate 'Go format' go_format_validate
  run_gate 'Go vet' go vet ./applications/platform-demo/...
  run_gate 'Go tests' go test ./applications/platform-demo/...
else
  not_applicable 'Go format/vet/test' 'application source begins in Phase 6; module ownership is reserved only'
fi

if find . -type f -name Dockerfile -not -path './.git/*' -not -path './.local/*' -print -quit | grep -q .; then
  run_gate 'Dockerfile lint' dockerfile_validate
else
  not_applicable 'Dockerfile lint' 'no Dockerfile exists'
fi

run_gate 'Locked GitHub Action references' python scripts/quality/check_action_pins.py
run_gate 'GitHub Actions syntax and semantics' actionlint
run_gate 'Markdown structure' markdown_validate
run_gate 'Gitleaks working tree and history' bash scripts/quality/secret-scan.sh

if ((${#failures[@]})); then
  printf '\n[FAIL] Phase 1 validation failed (%d gate(s)):\n' "${#failures[@]}" >&2
  printf '  - %s\n' "${failures[@]}" >&2
  exit 1
fi

echo '[PASS] All applicable repository validation gates passed.'
