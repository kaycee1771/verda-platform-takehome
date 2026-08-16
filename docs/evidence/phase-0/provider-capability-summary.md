# Verda Provider Capability Summary

- **Collected:** 2026-08-16
- **IaC engine:** Terraform 1.15.8
- **Provider address:** `registry.terraform.io/verda-cloud/verda`
- **Resolved provider:** 1.1.2 under `~> 1.0`
- **Provider verification:** Terraform reported a developer self-signed provider key; dependency checksums are captured in `.terraform.lock.hcl`.
- **Cloud resources declared or created:** None.

## Resource inventory

The exported schema exposes:

- `verda_instance`
- `verda_volume`
- `verda_volume_attachment`
- `verda_ssh_key`
- `verda_startup_script`
- `verda_container`
- `verda_container_registry_credentials`
- `verda_serverless_job`

It exposes **zero Terraform data sources**. Account-specific SKU, image, location, availability, and balance discovery must therefore use authenticated read-only Verda CLI or public API calls rather than Terraform data sources.

## Relevant schema observations

| Resource | Required inputs | Material optional inputs | Useful computed evidence |
|---|---|---|---|
| `verda_instance` | description, hostname, image, instance type | contract, existing volumes, location, OS volume, SSH keys, startup script, additional volumes | public IP, CPU, memory, storage, hourly price, status, OS volume ID |
| `verda_volume` | name, size, type | location | ID, attached instance, status, creation time |
| `verda_volume_attachment` | instance ID, volume ID | None | mount, fstab, and directory commands |
| `verda_ssh_key` | name, public key | None | ID and fingerprint |
| `verda_startup_script` | name, script | None | ID and creation time |

The instance schema supports nested OS-volume and additional-volume creation. The separate attachment resource is still preferable where independent lifecycle, attachment visibility, and `prevent_destroy` controls are required.

## Architecture consequences

- Terraform owns resource lifecycle; Verda CLI owns read-only discovery.
- The final module must output hourly price as observed state and reconcile it to the pre-apply cost model.
- Location must be explicit even though the provider marks it optional/computed; relying on a default would weaken reproducibility.
- Persistent data volumes should have an independent lifecycle and destruction protection.
- Provider documentation examples must be checked against the locked schema rather than copied blindly.
- Startup scripts are first-boot mechanisms; ongoing host convergence remains Ansible's responsibility.
