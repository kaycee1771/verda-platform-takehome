SHELL := /usr/bin/env bash

.DEFAULT_GOAL := help

.PHONY: help bootstrap-tools validate test verify status secret-scan pre-commit ci \
	collect-evidence cost-report destroy-plan infra-plan configure-hosts verify-hosts \
	verify-cluster bootstrap-gitops deploy-platform promote

help:
	@printf '%s\n' \
	  'Verda platform operator commands' \
	  '' \
	  '  make bootstrap-tools   Prepare the pinned validation toolchain' \
	  '  make validate          Validate repository configuration and manifests' \
	  '  make test              Run the application and repository test suites' \
	  '  make verify            Run read-only live platform verification' \
	  '  make status            Show the current submission-readiness summary' \
	  '  make collect-evidence  Collect sanitized live verification evidence' \
	  '  make cost-report       Print the current infrastructure cost envelope' \
	  '  make destroy-plan      Produce a reviewed destructive Terraform plan' \
	  '' \
	  'Optional lifecycle commands:' \
	  '  make infra-plan' \
	  '  make configure-hosts' \
	  '  make verify-hosts' \
	  '  make verify-cluster' \
	  '  make bootstrap-gitops' \
	  '  make deploy-platform' \
	  '  make promote FROM=dev TO=staging DIGEST=sha256:...'

bootstrap-tools:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/quality/bootstrap-tools.ps1

validate:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target validate

test:
	@python3 -m unittest discover -s tests/static -p 'test_*.py'
	@cd applications/platform-demo && go test ./...

verify:
	@bash scripts/verify-platform.sh

status:
	@python3 scripts/status.py

secret-scan:
	@bash scripts/quality/secret-scan.sh

pre-commit:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target pre-commit

ci:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target ci

collect-evidence:
	@bash scripts/collect-evidence.sh

cost-report:
	@bash scripts/cost-report.sh

destroy-plan:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/infra/phase2.ps1 -Target lifecycle-check -Cluster management

infra-plan:
	@bash scripts/provision.sh plan

configure-hosts:
	@bash scripts/configure.sh

verify-hosts:
	@pwsh -NoLogo -NoProfile -NonInteractive -File scripts/host/phase3.ps1 -Target verify -Cluster management

verify-cluster:
	@bash scripts/verify-cluster.sh

bootstrap-gitops:
	@bash scripts/bootstrap-gitops.sh

deploy-platform:
	@kubectl apply -k gitops/root

promote:
	@bash scripts/promote.sh "$(FROM)" "$(TO)" "$(DIGEST)"
