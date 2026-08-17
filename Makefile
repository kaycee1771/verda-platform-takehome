PWSH ?= pwsh

.DEFAULT_GOAL := help

.PHONY: help bootstrap-tools install-hooks validate validate-negative pre-commit secret-scan ci discover \
	phase0-validate phase0-tools phase0-preflight phase0-discover-account phase0-provider-schema \
	infra-init infra-plan infra-apply infra-repair-node-02-plan infra-repair-node-02-apply infra-lifecycle-check inventory configure verify-hosts verify-cluster \
	bootstrap-gitops platform-status stage-a-verify register-clusters stage-b-verify \
	app-test app-build supply-chain-verify promote verify fault backup restore-test \
	cost-report collect-evidence sanitize-evidence destroy

help:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/make-help.ps1

bootstrap-tools:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/bootstrap-tools.ps1

install-hooks:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/install-hooks.ps1

validate:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target validate

validate-negative:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target negative

pre-commit:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target pre-commit

secret-scan:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target secret-scan

ci:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/run-quality.ps1 -Target ci

discover:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/discover-verda.ps1

phase0-validate:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/validate.ps1

phase0-tools:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/discover-tools.ps1

phase0-preflight:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/discover-verda.ps1

phase0-discover-account:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/discover-verda.ps1 -QueryAccount -ConfirmReadOnly -OutputPath evidence/phase-0/verda-discovery.local.json

phase0-provider-schema:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/phase0/export-provider-schema.ps1 -AllowProviderDownload -OutputPath evidence/phase-0/provider-schema.local.json

infra-init infra-plan infra-apply infra-repair-node-02-plan infra-repair-node-02-apply infra-lifecycle-check inventory configure verify-hosts verify-cluster bootstrap-gitops platform-status stage-a-verify register-clusters stage-b-verify app-test app-build supply-chain-verify promote verify fault backup restore-test cost-report collect-evidence sanitize-evidence destroy:
	@$(PWSH) -NoLogo -NoProfile -NonInteractive -File scripts/quality/phase-gate.ps1 -Target "$@" -Arguments "CLUSTER=$(CLUSTER) FROM=$(FROM) TO=$(TO) DIGEST=$(DIGEST) TEST=$(TEST) TARGET=$(TARGET) CONFIRM=$(CONFIRM)"
