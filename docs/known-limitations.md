# Known Limitations

## Phase 0 outcome and deferred gates

| Limitation | State | Consequence | Required resolution |
|---|---|---|---|
| Cloud API credentials do not exist in the current project/profile | FUTURE BLOCKER — Phase 2 | Terraform cannot authenticate | Create a least-privilege credential immediately before Phase 2 and keep it outside Git/logs |
| Current self-service surfaces expose no private network, firewall/security group, managed LB, floating/VIP, or DNS | ACCEPTED RESIDUAL | Path A cannot be implemented; the default API endpoint is not truly HA | Use ADR-0005 Path B; live-test WireGuard, MTU, firewall, multi-node ingress, and break glass |
| Object Storage Access Keys are not exposed in this project's Credentials page | FUTURE BLOCKER — Phase 5 | Verda S3 cannot yet back Loki/Velero/Longhorn | Confirm entitlement with Verda or select the ADR-approved external S3 fallback |
| Object-storage path style, TLS, lifecycle, request/egress pricing, and application compatibility are unverified | FUTURE BLOCKER — Phase 5 | Backup/logging configuration could fail or exceed allowance | Run non-destructive compatibility and pricing checks before use |
| Public-IP allocation and deletion behavior is documented/schema-visible but not live-tested | FUTURE BLOCKER — Phase 2 exit | Reachability and teardown claims are not yet evidence-backed | Capture sanitized apply/inventory/connectivity/destroy evidence |
| No candidate-controlled domain is supplied | NON-BLOCKING FALLBACK | Names depend on instance-address-derived DNS | Use documented `sslip.io` fallback and include exact residual behavior |
| No GitHub remote is configured in this checkout | PHASE 1 EXTERNAL FOLLOW-UP | Workflow syntax and local CI parity are proven, but no hosted run or branch-protection state can be captured yet | Push to the final repository, replace the CODEOWNERS placeholder, require `Validate repository`, and retain the first successful run |

## Phase 1 quality-system boundaries

- Git, GNU Make, PowerShell 7, and a Docker Linux daemon are bootstrap prerequisites; the repository
  reports them and never installs or upgrades workstation packages silently.
- Bootstrap requires public network access to checksummed, version-pinned upstream sources. Positive
  validation, negative tests, pre-commit, CI parity, and secret scanning run with networking disabled.
- The repository has no configured GitHub owner or remote, so `CODEOWNERS` deliberately contains an
  explicit placeholder instead of guessing an account. Replace it before publishing the repository.
- Placeholder files and future-phase workflows fail closed and do not represent implemented platform
  services, application code, cloud state, or live operational evidence.

## Provider limitations confirmed from schema 1.1.2

- No Terraform data sources are exposed.
- No Terraform resources are exposed for private networks, firewalls/security groups, load balancers, floating/virtual IPs, DNS, object-storage buckets, or object-storage credentials.
- Account inventory cannot be modeled as data sources; exact values are pinned inputs and revalidated before apply.
- Object-storage provisioning, DNS, and networking require a documented manual or alternate automation boundary if they later become available.
- The provider source still describes beta status; exact plans, replacement semantics, imports, and drift require focused tests.

## Architectural limitations accepted for the take-home

- Stage A co-locates management services and application environments; a whole-cluster loss removes both.
- Both stages use schedulable control-plane nodes; platform/workload pressure can compete with etcd and API processes.
- Dev, staging, and production are namespaces in one workload cluster, not independent security/control-plane boundaries.
- Longhorn replication does not make stateful services application-level HA and is not an off-cluster backup.
- The Path B primary API/registration address is a control-path SPOF for default clients and new joins; direct-node kubeconfigs are break glass, not a managed HA endpoint.
- WireGuard secures internode traffic but does not create a cloud-private failure domain or managed DDoS/firewall service.
- Two clusters in one Verda region/account are not regional disaster recovery.

These limitations remain visible until replaced by live evidence or a superseding ADR.
