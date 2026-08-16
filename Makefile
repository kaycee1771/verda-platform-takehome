PWSH ?= pwsh

.PHONY: phase0-validate phase0-tools phase0-preflight phase0-discover-account phase0-provider-schema

phase0-validate:
	$(PWSH) -NoProfile -File scripts/phase0/validate.ps1

phase0-tools:
	$(PWSH) -NoProfile -File scripts/phase0/discover-tools.ps1

phase0-preflight:
	$(PWSH) -NoProfile -File scripts/phase0/discover-verda.ps1

phase0-discover-account:
	$(PWSH) -NoProfile -File scripts/phase0/discover-verda.ps1 -QueryAccount -ConfirmReadOnly -OutputPath evidence/phase-0/verda-discovery.local.json

phase0-provider-schema:
	$(PWSH) -NoProfile -File scripts/phase0/export-provider-schema.ps1 -AllowProviderDownload -OutputPath evidence/phase-0/provider-schema.local.json
