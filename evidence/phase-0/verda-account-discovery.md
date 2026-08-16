# Evidence: Read-Only Verda Account Discovery

- Collected: 2026-08-16
- Surfaces: authenticated Verda console, Verda CLI 1.8.1, provider 1.1.2 schema, current official Verda documentation
- Browser actions: navigation, read-only filters/selections, and modal inspection only
- Credential/key/coupon values captured: no
- Cloud mutation attempted: no
- Resources observed running: none; billing showed $0.00/hour

## Result

**PASS for the Phase 0 discovery gate.** The authenticated console supplied current project catalog, availability, credential-surface, balance, and networking evidence. The local CLI profile remains unauthenticated and is explicitly gated before Phase 2.

| Query group | Sanitized observed result |
|---|---|
| Project balance | $115.67 USD |
| Current usage | $0.00/hour |
| CPU selection | `CPU.4V.16G`; 4 vCPU; 16 GiB RAM; $0.02790/hour |
| Availability | Selected shape visible in FIN-01, FIN-02, FIN-03 |
| Selected location | FIN-03 |
| OS selection | Ubuntu 24.04 + Minimal Image |
| OS configuration ID | `77edfb23-bb0d-41cc-a191-dccae45d96fd` |
| Volume selection | NVMe; $0.20/GiB-month; 50 GiB live quote $0.01370/hour |
| Volume locations/attachment | FIN-01/02/03; mounted to one instance at a time |
| Cloud API credentials | None in the current project |
| SSH/registry credentials | None in the current project |
| Object-storage credentials | Not configured; documented Object Storage Access Keys section absent |
| Network controls | No private-network, firewall/security-group, LB, floating/VIP, or DNS link/field exposed |
| Provider resources/data sources | 8 / 0 |

The image UUID is a catalog configuration identifier, not an account identifier or secret. This committed evidence contains no project ID, user identity, coupon, API credential, SSH key, object-storage key, public IP, or secret.

## CLI result

The allowlisted script ran with `-ConfirmReadOnly` and wrote only an ignored redacted local JSON file. Doctor and local status commands passed. Account-backed queries returned `AUTH_ERROR` because the active profile has no Client ID/Secret. This is retained as truthful evidence and becomes GATE-006 before Terraform.

## Decision supported

- Pin `CPU.4V.16G`, FIN-03, Ubuntu 24.04 Minimal, and NVMe.
- Use on-demand capacity for all control-plane/etcd nodes.
- Accept ADR-0005 Path B and defer live network tests until nodes exist.
- Cap the seven-day Stage A envelope at $50.51.
- Block off-cluster Verda S3 use until entitlement and compatibility are proven.
