# Known Limitations

## Phase 0 outcome and deferred gates

| Limitation | State | Consequence | Required resolution |
|---|---|---|---|
| Time-bound project Cloud API credential has no exposed resource scopes | ACCEPTED RESIDUAL — Phase 2 | Project scope is the narrowest self-service boundary | Keep it process-only, expire after review, and revoke during teardown |
| Current self-service surfaces expose no private network, firewall/security group, managed LB, floating/VIP, or DNS | ACCEPTED RESIDUAL | Path A cannot be implemented; the later default API endpoint will not be truly HA | ADR-0005 Path B host mesh/MTU/firewall are live-proven; test multi-node ingress, direct kubeconfig, and endpoint failure in their owning phases |
| Object storage was enabled after support review, but provider 1.1.2 cannot own its bucket or credential | RESOLVED FOR PHASE 4 / ACCEPTED RESIDUAL | Management etcd off-cluster snapshots pass; lifecycle and teardown remain manual | Keep the provider-gap exception, rotate/revoke the scoped credential, and delete or retain objects deliberately during teardown |
| Object-storage application compatibility, lifecycle policy, request/egress pricing, and later-service credentials are unverified | FUTURE BLOCKER — Phases 11, 13, and 14 | Loki/Velero/Longhorn backup configuration could fail or exceed allowance | Run non-destructive compatibility and pricing checks with separately scoped credentials before each later use |
| Initial duplicate public-address allocation | RESOLVED — Phase 2 | The first server-02 could not be reached independently | An exact compute/OS-only replacement preserved its data volume; three unique endpoints and hostname-bound SSH now pass |
| Provider 1.1.2 returns image_type after a UUID create request | MITIGATED PROVIDER DEFECT | Initial apply marked instances tainted despite successful creation | ADR 0012 pins both representations, validates the live mapping, and the final plan proves zero drift after taint recovery |
| No candidate-controlled domain is supplied | NON-BLOCKING FALLBACK | Names depend on instance-address-derived DNS | Use documented `sslip.io` fallback and include exact residual behavior |
| Current SSH source is one operator public `/32` | ACCEPTED RESIDUAL — Phase 3 | Operator address change denies new SSH sessions by design | Re-run the rollback-protected allowlist workflow from console/recovery; use VPN/bastion in production |
| Operator source changed after the Phase 3 `/32` restriction | RESOLVED EVENT / ACCEPTED RESIDUAL | The exact-source control failed closed and the authorized timed-rollback recovery restored access; future changes will deny sessions again | Repeat the exact rollback-protected workflow; never broaden SSH globally; use a durable VPN/bastion in production |
| Phase 3 Cloud API credential was visibly supplied in an operator-controlled image | ROTATION REQUIRED | The value is outside Git but should be treated as exposed after its bounded use | Delete the source image and revoke/rotate the credential before handoff or immediately after no further authenticated work is required |

## Phase 1 quality-system boundaries

- Git, GNU Make, PowerShell 7, and a Docker Linux daemon are bootstrap prerequisites; the repository
  reports them and never installs or upgrades workstation packages silently.
- Bootstrap requires public network access to checksummed, version-pinned upstream sources. Positive
  validation, negative tests, pre-commit, CI parity, and secret scanning run with networking disabled.
- The repository is public by explicit owner authorization so GitHub Free can enforce protection.
  `main` requires the GitHub Actions validation check and pull requests; CODEOWNERS names the verified
  owner. Public visibility is intentional and must not be changed without revalidating governance.
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
- The Path B primary API/registration address remains a control-path SPOF for default clients and new joins; direct-node kubeconfigs are break glass, not a managed HA endpoint. The controlled failure drill proved the expected default-endpoint loss and direct-node recovery path, but did not create a managed HA endpoint.
- WireGuard secures internode traffic but does not create a cloud-private failure domain or managed DDoS/firewall service.
- Two clusters in one Verda region/account are not regional disaster recovery.

These limitations remain visible until replaced by live evidence or a superseding ADR.
