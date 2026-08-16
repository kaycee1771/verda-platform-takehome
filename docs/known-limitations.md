# Known Limitations

## Phase 0 blockers

| Limitation | State | Consequence | Required resolution |
|---|---|---|---|
| Verda API credentials are absent from the current shell/profile | BLOCKING | Account inventory cannot run | Configure credentials outside Git and rerun read-only discovery |
| Assignment credit and current balance are unverified | BLOCKING | Stage A affordability cannot be proven | Confirm coupon application and capture sanitized balance/cost evidence |
| CPU shapes, prices, capacity, and OS image IDs are unknown | BLOCKING | Node selection and Stage A cost envelope are not credible | Query current account inventory and choose exact values |
| Account networking features are unknown | BLOCKING | Endpoint and internode network strategy cannot be accepted | Inspect API/CLI/console for private network, firewall, LB, floating/VIP support |
| Candidate base domain is not supplied | NON-BLOCKING FALLBACK | Public names cannot yet be final | Use documented `sslip.io` fallback until a controlled domain is available |

## Provider limitations confirmed from schema 1.1.2

- No Terraform data sources are exposed.
- No Terraform resources are exposed for private networks, firewalls/security groups, load balancers, floating/virtual IPs, DNS, object-storage buckets, or object-storage credentials.
- Account discovery must use authenticated read-only CLI/API/console paths.
- Object-storage provisioning, DNS, and networking may require a documented manual or alternate automation boundary if the account exposes them but the provider does not.
- The provider is marked beta in its source repository; exact plans and drift behavior require focused tests before production use.

## Architectural limitations accepted for the take-home

- Stage A co-locates management services and application environments; a whole-cluster loss removes both.
- Both stages use schedulable control-plane nodes; platform/workload pressure can compete with etcd and API processes.
- Dev, staging, and production are namespaces in one workload cluster, not independent security/control-plane boundaries.
- Longhorn replication does not make stateful services application-level HA and is not an off-cluster backup.
- No public endpoint is described as HA until failure behavior is tested against an observed Verda mechanism.
- Two clusters in one Verda region/account are not regional disaster recovery.

These limitations remain visible until replaced by evidence or an approved ADR.
