# Verda Capability Discovery Report

## Collection metadata

| Item | Value |
|---|---|
| Review date | 2026-08-16 |
| Terraform | 1.15.8 (`windows_amd64`) |
| Verda CLI | 1.8.1 (`windows/amd64`, SDK 1.4.2) |
| Provider | `registry.terraform.io/verda-cloud/verda` 1.1.2 |
| Provider lock SHA-256 | `83F8120C9E5AE6B6CFE351F894838A42E4ABF218B363F5E09747FFE9386B07FC` |
| Schema export SHA-256 | `A3669F06A9DCEEEDB3DF29F245E1E3B17A86D37E579B8F75EEC07FBEF662FE5E` |
| Account inspection | Authenticated Verda console plus sanitized local CLI status |
| Cloud API authentication | No active profile or Cloud API key; required before Phase 2 |
| Cloud mutation | None attempted |

## Exact provider 1.1.2 surface

The locally initialized, lockfile-selected schema exposes exactly these resources:

- `verda_instance`
- `verda_volume`
- `verda_volume_attachment`
- `verda_ssh_key`
- `verda_startup_script`
- `verda_container`
- `verda_container_registry_credentials`
- `verda_serverless_job`

It exposes **zero data sources**. It exposes no resource for private networking, firewall/security groups, load balancers, floating/virtual IPs, DNS, object-storage buckets, or object-storage credentials. No such provider resource will be invented.

### Compute/storage attributes relevant to later modules

`verda_instance` requires `description`, `hostname`, `image`, and `instance_type`; it supports optional/computed `location`, `contract`, `pricing`, `is_spot`, `ssh_key_ids`, nested `os_volume`, nested `volumes`, `existing_volumes`, and `startup_script_id`. Computed evidence includes `ip`, CPU, memory, storage, hourly price, status, OS-volume ID, and GPU metadata.

`verda_volume` requires `name`, `size`, and `type`, with optional `location`. `verda_volume_attachment` requires instance and volume IDs and exposes mount/fstab/directory commands. Exact constraints remain in the ignored raw schema and must be re-read when Phase 2 modules are authored.

## Current account catalog and selection

| Capability | Observed current-account result | Phase 0 decision |
|---|---|---|
| Project balance/run rate | $115.67 / $0.00 per hour | Seven-day envelope may use at most $50.51 |
| CPU shape | `CPU.4V.16G`, 4 vCPU, 16 GiB, $0.02790/hour | Selected on-demand; never spot for etcd/control plane |
| CPU availability | Selected shape visible in FIN-01, FIN-02, FIN-03 | Select `FIN-03`; recheck immediately before apply |
| OS image | Ubuntu 24.04 + Minimal Image; configuration ID `77edfb23-bb0d-41cc-a191-dccae45d96fd`; console family code `OS-eGdudzqj` | Pin the exact configuration ID; verify provider plan input before apply |
| Root/data storage | NVMe; single-instance attachment; FIN-01/02/03; $0.20/GiB-month | 80 GiB root plus 100 GiB data per node |
| Public IP | Provider computes `ip`; official instance docs describe public-IP access; console exposes no address/network choice | Treat allocation as provider-managed; prove lifecycle and reachability after apply |
| Existing resources | No instance or block-volume usage; billing run rate $0.00/hour | Phase 0 inventory remains empty |
| Cloud API/SSH keys | No Cloud API credentials and no SSH keys | Create least privilege outside Git before Phase 2 |
| Registry credentials | None | Harbor remains the assignment registry; credential creation deferred |
| Object-storage credentials | CLI reports unconfigured; current project Credentials page has no Object Storage Access Keys section | Entitlement/approved external S3 fallback blocks Phase 5 |

The exact image UUID is a public catalog configuration identifier, not an account credential. No project ID, user identity, coupon, credential, or key material is committed.

## Network and endpoint capability boundary

Three independent surfaces agree:

1. Provider 1.1.2 exposes no private-network, firewall/security-group, load-balancer, floating/VIP, or DNS resource.
2. CLI 1.8.1 exposes no command family for those capabilities.
3. The authenticated project navigation and instance deployment form expose no link or field matching network, firewall, security group, load balancer, floating/virtual IP, VIP, or DNS.

This is evidence about the current self-service account and automation surfaces, not a universal claim about every Verda offering. ADR-0005 therefore accepts blueprint Path B: public instance addresses, a host WireGuard mesh for internode traffic, a designated registration/API endpoint with direct-node break glass, and multi-node ingress exposure. The designated endpoint is not described as HA. Live MTU, peer routing, firewall, port, address-lifecycle, and failure tests remain mandatory after instances exist.

## Object-storage and billing findings

- Current official documentation describes S3-compatible storage with credentials separate from Cloud API credentials, default endpoint `https://objects.fin-03.verda.storage`, and region `us-east-1`.
- The current project does not expose the documented Object Storage Access Keys section, and local S3 status is unconfigured.
- Bucket creation, least privilege, path-style behavior, TLS trust, lifecycle/retention, request/egress pricing, and application compatibility remain **UNVERIFIED** and block Phase 5.
- Official pricing and the live volume dialog agree on NVMe at $0.20/GiB-month; a 50 GiB volume is quoted at $0.01370/hour.
- Pay-as-you-go is prepaid in ten-minute increments. At zero balance, instances can be discontinued and volumes deleted; recovery is documented for 96 hours.

## Read-only CLI result

The allowlisted discovery script ran with `-ConfirmReadOnly` and wrote an ignored, redacted local JSON file. Local doctor/status commands passed, but account-backed queries returned `AUTH_ERROR` because `verda auth login` had not produced an active Cloud API profile. This does not invalidate authenticated console evidence, but it is a hard prerequisite for Terraform in Phase 2.

## Documentation/schema discrepancies

1. The provider source README still says the provider is not in Terraform Registry, while Terraform Registry and current Verda documentation publish it there. The registry plus successful locked initialization govern.
2. The generic Terraform instance page describes example fields absent from exact provider 1.1.2. The exported schema governs.
3. Official docs refer conceptually to firewall rules, but provider 1.1.2, CLI 1.8.1, and this project console expose no self-service firewall resource/control.
4. Official object-storage docs describe a Credentials section that is absent from this project's current Credentials page. Entitlement is not assumed.

## Phase 0 conclusion

The CPU shape, image, location, volume type/rate, balance, billing semantics, provider surface, and current networking limitations are known. Path B and the Stage A envelope are selected without creating a resource. Phase 0 account discovery is PASS; missing Cloud API credentials and object-storage entitlement are explicit future-phase gates.
