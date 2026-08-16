# Risk Register

Ratings are qualitative: likelihood and impact are Low, Medium, or High. Owners must update triggers and residual risk as evidence becomes available.

| ID | Risk | Likelihood | Impact | Trigger | Mitigation | Contingency | Owner |
|---|---|---|---|---|---|---|---|
| R-001 | Credits expire or are exhausted before assessment | Medium | High | Forecast exceeds 70% of available credit | Price before apply; use budgets; right-size retention; avoid idle GPU | Switch to lean topology and shorten uptime window | Platform owner |
| R-002 | No supported HA load balancer/floating/VIP endpoint is available | Unknown | High | Authenticated account discovery exposes only VM public IPs | Inspect account/API/console; run ingress on all nodes; document endpoint behavior | Use a designated endpoint with direct-node break glass and declare the SPOF | Platform owner |
| R-003 | Inter-node traffic traverses public networking | Unknown | High | No private peer addresses are present | Prefer private network; otherwise WireGuard, peer allowlist, and MTU tests | Reduce exposed ports and document limitation | Security owner |
| R-004 | Co-located platform components cause resource pressure | Medium | High | Pending pods, eviction, or sustained saturation | Capacity model, requests/limits, retention bounds, priority classes | Disable bonus components or resize nodes | Platform owner |
| R-005 | Longhorn prerequisites or network latency make storage unstable | Medium | High | Volume replicas degrade or rebuild slowly | Dedicated disks, prerequisite validation, anti-affinity, health alerts | Use node-local storage with explicit availability gap | Storage owner |
| R-006 | DNS or certificate issuance is unavailable | Medium | Medium | ACME validation or DNS configuration fails | Select DNS before deployment; test HTTP-01 path | Use a temporary DNS name and document trust limitations | Platform owner |
| R-007 | Credentials or account metadata leak into Git or CI logs | Low | Critical | Secret scanner finding or unexpected debug output | Environment variables, ignored local evidence, no debug, secret scanning | Revoke immediately, purge history, rotate all derived credentials | Security owner |
| R-008 | Kubernetes, Rancher, or Helm chart versions are incompatible | Medium | High | CRDs fail, controllers crash, or support matrix mismatch | Pin versions and verify compatibility before bootstrap | Roll back to tested version set | Platform owner |
| R-009 | Backups exist but cannot restore | Medium | High | Restore test fails or recovery material is absent | Automate restore drill and checksum verification | Rebuild declarative state and document lost data class | Recovery owner |
| R-010 | Bonus work destabilizes core requirements | Medium | High | Core acceptance matrix is not green before bonus start | Core-first gate; bonuses isolated behind overlays | Remove GPU/Kueue/signing scope | Delivery owner |
| R-011 | Provider documentation differs from the installed schema | Medium | Medium | Plan rejects documented attributes | Export provider schema and pin lock file | Use verified schema and record documentation gap | IaC owner |
| R-012 | Assessor access is either insecure or too difficult | Medium | High | Access needs admin assistance or broad public ports | Least-privilege accounts, scripted checks, SSH tunnel fallback | Time-bounded ingress allowlist and guided session | Security owner |
| R-013 | Beta provider behavior or documentation/schema drift causes unsafe plans | Medium | High | Documentation fields are absent from schema or plan shows unexpected replacement | Exact `= 1.1.2` pin, lockfile, schema-derived modules, focused plan tests | Stop and use verified CLI/manual exception with ADR; never invent a resource | IaC owner |
| R-014 | Prepaid balance reaches zero and Verda removes instances/volumes | Low/Unknown | Critical | Balance falls below the documented safe operating buffer | Cost ledger, alerts, 15% contingency, at least 12-hour balance buffer | Preserve evidence/backups and stop workloads before threshold | Platform owner |
| R-015 | Stage B begins before Stage A is reproducible | Medium | High | Multi-cluster work starts with a red mandatory row | Enforce Stage B decision gate in status and review | Retain rigorously proven Stage A and document Stage B only | Delivery owner |

## Review cadence

- Reassess before every phase gate.
- Add a risk when a workaround creates a new failure mode.
- Close a risk only with evidence; a documented limitation remains an accepted residual risk, not a closed risk.
