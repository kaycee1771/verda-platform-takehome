# Risk Register

Ratings are qualitative: likelihood and impact are Low, Medium, or High. Owners must update triggers and residual risk as evidence becomes available.

| ID | Risk | Likelihood | Impact | Trigger | Mitigation | Contingency | Owner |
|---|---|---|---|---|---|---|---|
| R-001 | Credits expire or are exhausted before assessment | Low | High | Forecast exceeds 70% of the verified $115.67 balance | $50.51 Stage A envelope, daily reconciliation, lean retention, no idle GPU | Shorten uptime and preserve evidence before teardown | Platform owner |
| R-002 | No supported HA load balancer/floating/VIP endpoint is available | High/Observed | High | Current provider, CLI, and project UI expose none | ADR-0005 Path B, ingress on all nodes, direct-node break glass, honest endpoint claim | Replace the designated endpoint and update clients; retain documented SPOF | Platform owner |
| R-003 | Inter-node traffic traverses public networking | High/Observed path | High | Current self-service surface has no private-network control | WireGuard, exact peer allowlist, host firewall, MTU/port tests | Stop bootstrap if encrypted peer matrix is not green | Security owner |
| R-004 | Co-located platform components cause resource pressure | Medium | High | Pending pods, eviction, or sustained saturation | Capacity model, requests/limits, retention bounds, priority classes | Disable bonus components or resize nodes | Platform owner |
| R-005 | Longhorn prerequisites or network latency make storage unstable | Medium | High | Volume replicas degrade or rebuild slowly | Dedicated disks, prerequisite validation, anti-affinity, health alerts | Use node-local storage with explicit availability gap | Storage owner |
| R-006 | DNS or certificate issuance is unavailable | Medium | Medium | `sslip.io` resolution or HTTP-01 validation fails | Pin the fallback contract and test resolution/ACME before public handoff | Use documented direct-node TLS access or another approved temporary DNS service | Platform owner |
| R-007 | Credentials or account metadata leak into Git or CI logs | Low | Critical | Secret scanner finding or unexpected debug output | Environment variables, ignored local evidence, no debug, secret scanning | Revoke immediately, purge history, rotate all derived credentials | Security owner |
| R-008 | Kubernetes, Rancher, or Helm chart versions are incompatible | Medium | High | CRDs fail, controllers crash, or support matrix mismatch | Pin versions and verify compatibility before bootstrap | Roll back to tested version set | Platform owner |
| R-009 | Backups exist but cannot restore | Medium | High | Restore test fails or recovery material is absent | Automate restore drill and checksum verification | Rebuild declarative state and document lost data class | Recovery owner |
| R-010 | Bonus work destabilizes core requirements | Medium | High | Core acceptance matrix is not green before bonus start | Core-first gate; bonuses isolated behind overlays | Remove GPU/Kueue/signing scope | Delivery owner |
| R-011 | Provider documentation differs from the installed schema | Medium | Medium | Plan rejects documented attributes | Export provider schema and pin lock file | Use verified schema and record documentation gap | IaC owner |
| R-012 | Assessor access is either insecure or too difficult | Medium | High | Access needs admin assistance or broad public ports | Least-privilege accounts, scripted checks, SSH tunnel fallback | Time-bounded ingress allowlist and guided session | Security owner |
| R-013 | Beta provider behavior or documentation/schema drift causes unsafe plans | Medium | High | Documentation fields are absent from schema or plan shows unexpected replacement | Exact `= 1.1.2` pin, lockfile, schema-derived modules, focused plan tests | Stop and use verified CLI/manual exception with ADR; never invent a resource | IaC owner |
| R-014 | Prepaid balance reaches zero and Verda removes instances/volumes | Low | Critical | Balance falls below 12 hours of run rate or envelope reaches 85% | Cost ledger, $50.51 cap, 15% contingency, daily checks, at least 12-hour buffer | Preserve evidence/backups and tear down before threshold | Platform owner |
| R-015 | Stage B begins before Stage A is reproducible | Medium | High | Multi-cluster work starts with a red mandatory row | Enforce Stage B decision gate in status and review | Retain rigorously proven Stage A and document Stage B only | Delivery owner |
| R-016 | Current project lacks Verda object-storage entitlement | High/Observed | High | Credentials page has no Object Storage Access Keys section | Gate Phase 5; confirm entitlement early; keep external S3 fallback explicit | Use approved third-party S3 or reduce claims; never use in-cluster-only backup as DR | Recovery owner |
| R-017 | Operator address changes after exact `/32` SSH restriction | Medium | High | New strict SSH sessions time out while nodes remain healthy | Runtime-derived canonical `/32`, five-minute firewall rollback, console recovery, external host-key pins | Update the allowlist through the same guarded playbook; move to VPN/bastion for durable access | Security owner |
| R-018 | A time-bound Cloud API credential was visible in an operator-provided local image | Observed | Critical | Image remains available or credential survives the bounded work window | Values stayed process-only in automation, were never logged/committed, and all evidence is sanitized | Delete the image and revoke/rotate the credential; investigate immediately if secret scanning or account activity is unexpected | Security owner |

## Review cadence

- Reassess before every phase gate.
- Add a risk when a workaround creates a new failure mode.
- Close a risk only with evidence; a documented limitation remains an accepted residual risk, not a closed risk.
