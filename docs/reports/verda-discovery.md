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
| Account authentication | BLOCKED — no current API credentials/profile |
| Console session check | BLOCKED — in-app browser and connected Chrome both redirect to sign-in |
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

`verda_instance` requires `description`, `hostname`, `image`, and `instance_type`; it supports optional/computed `location`, `contract`, `pricing`, `is_spot`, `ssh_key_ids`, nested `os_volume`, nested `volumes`, `existing_volumes`, and `startup_script_id`. Computed evidence includes `ip`, `cpu`, `memory`, `storage`, `price_per_hour`, `status`, `os_volume_id`, and GPU metadata.

`verda_volume` requires `name`, `size`, and `type`, with optional `location`. `verda_volume_attachment` requires an instance ID and volume ID and exposes mount/fstab/directory commands. Exact nested constraints remain in the ignored raw schema and must be re-read when Phase 2 modules are authored.

## Authenticated account query results

The allowlisted discovery workflow was run with explicit read-only confirmation. Local doctor/status commands completed, while every API-backed inventory/cost query returned an authentication error.

| Capability | Query path | Result |
|---|---|---|
| Locations | `verda locations` | BLOCKED — no credentials |
| CPU types/specifications/prices | `verda instance-types --cpu` | BLOCKED — no credentials |
| OS images | `verda images` | BLOCKED — no credentials |
| FIN-01/02/03 availability | `verda availability --location …` | BLOCKED — no credentials |
| Existing volumes | `verda volume list` | BLOCKED — no credentials |
| Account/running cost/balance | `verda status`, `verda cost …` | BLOCKED — no credentials |
| Object-storage credential status | `verda object-storage show` | Command succeeds without exposing secrets; live S3 access unverified |
| Registry credential status | `verda registry show` | Command succeeds without exposing secrets; capability not selected for the assignment registry |

Credential-presence booleans were false; values were never captured. Raw redacted output is local and ignored.

A read-only console-session check was also attempted in both available browser surfaces. Each redirected to `https://console.verda.com/signin`; no email/password was entered and no login, credential creation, billing action, or resource mutation was attempted.

## Official documentation findings

- Verda’s current Terraform pages recommend `verda-cloud/verda ~> 1.0`, environment-variable authentication, and exact schema inspection.
- Terraform Registry reports 1.1.2 as current on the review date.
- Verda CLI documentation identifies account-backed commands for locations, types/prices, images, and availability.
- Verda documents persistent NVMe block volumes that survive instance deletion; volumes must be located with compute and are single-attachment for moves between instances.
- Verda object storage is S3-compatible and uses credentials separate from API credentials. The CLI currently documents default endpoint `https://objects.fin-03.verda.storage` and region `us-east-1`; exact account endpoint, TLS, path-style behavior, bucket controls, and compatibility tests remain unverified.
- Verda’s billing documentation describes prepaid ten-minute pay-as-you-go intervals and warns of resource discontinuation/data deletion at zero balance.
- RKE2’s current HA documentation requires a fixed registration address and recommends an odd number of three server nodes. RKE2 supports bundled Cilium and Hubble.

## Documentation/schema discrepancies

1. The provider repository README still says the provider is not in Terraform Registry, while Terraform Registry and Verda’s current documentation publish it there. The registry plus successful locked initialization govern.
2. Verda’s generic Terraform instance page describes example fields such as `disk_size_gb` and `startup_script`; those names are absent from the exact 1.1.2 `verda_instance` schema. The schema’s nested `os_volume` and `startup_script_id` govern.
3. Official Terraform documentation refers conceptually to firewall rules, but provider 1.1.2 exposes no firewall resource. No firewall automation boundary is selected until the account/API/console capability is observed.

## Endpoint decision state

ADR-0005 remains **Proposed**. Preferred Path A is a proven Verda private node network plus a supported HA L4/floating/private virtual endpoint. If unavailable, Path B is a host WireGuard mesh plus a documented primary API endpoint, direct-node break-glass kubeconfigs, and multi-node ingress exposure. DNS round robin is not called an HA load balancer.

## Blocker resolution

Recommended path: configure least-privilege Verda API credentials outside the repository, verify the assignment credit in the selected project, rerun `make phase0-discover-account`, then manually inspect only those console/API capabilities not represented by CLI/provider. No cloud resource should be created for discovery.
