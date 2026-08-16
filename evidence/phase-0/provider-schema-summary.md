# Evidence: Verda Provider Schema 1.1.2

- Collected: 2026-08-16
- Engine: Terraform 1.15.8
- Provider: `registry.terraform.io/verda-cloud/verda` 1.1.2
- Provider lock SHA-256: `83F8120C9E5AE6B6CFE351F894838A42E4ABF218B363F5E09747FFE9386B07FC`
- Raw schema SHA-256: `A3669F06A9DCEEEDB3DF29F245E1E3B17A86D37E579B8F75EEC07FBEF662FE5E`
- Resources declared by discovery configuration: 0
- Cloud resources created/changed: 0

## Mechanically observed surface

```text
verda_container
verda_container_registry_credentials
verda_instance
verda_serverless_job
verda_ssh_key
verda_startup_script
verda_volume
verda_volume_attachment
```

Data sources: **0**.

Absent resource categories: private network, firewall/security group, load balancer, floating/virtual IP, DNS, object-storage bucket, object-storage credential.

## Verification command

```powershell
pwsh -NoProfile -File scripts/phase0/export-provider-schema.ps1 `
  -AllowProviderDownload `
  -OutputPath evidence/phase-0/provider-schema.local.json
```

The detailed reviewed interpretation is `docs/reports/verda-discovery.md`. The ignored raw schema, not generic examples, governs Phase 2 module authoring.
