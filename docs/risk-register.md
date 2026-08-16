# Risk Register

Ratings are qualitative: likelihood and impact are Low, Medium, or High. Owners must update triggers and residual risk as evidence becomes available.

| ID | Risk | Likelihood | Impact | Trigger | Mitigation | Contingency | Owner |
|---|---|---|---|---|---|---|---|
| R-001 | Credits expire or are exhausted before assessment | Medium | High | Forecast exceeds 70% of available credit | Price before apply; use budgets; right-size retention; avoid idle GPU | Switch to lean topology and shorten uptime window | Platform owner |
| R-002 | No managed HA load balancer is available | High | High | Account/provider discovery exposes only VM public IPs | Run ingress on all nodes; document endpoint model; use health-aware DNS if available | Use one designated ingress IP and declare the SPOF | Platform owner |
| R-003 | Inter-node traffic traverses public networking | Medium | High | No private peer addresses are present | Peer allowlist, encryption where supported, explicit MTU test | Reduce exposed ports and document limitation | Security owner |
| R-004 | Co-located platform components cause resource pressure | Medium | High | Pending pods, eviction, or sustained saturation | Capacity model, requests/limits, retention bounds, priority classes | Disable bonus components or resize nodes | Platform owner |
| R-005 | Longhorn prerequisites or network latency make storage unstable | Medium | High | Volume replicas degrade or rebuild slowly | Dedicated disks, prerequisite validation, anti-affinity, health alerts | Use node-local storage with explicit availability gap | Storage owner |
| R-006 | DNS or certificate issuance is unavailable | Medium | Medium | ACME validation or DNS configuration fails | Select DNS before deployment; test HTTP-01 path | Use a temporary DNS name and document trust limitations | Platform owner |
| R-007 | Credentials or account metadata leak into Git or CI logs | Low | Critical | Secret scanner finding or unexpected debug output | Environment variables, ignored local evidence, no debug, secret scanning | Revoke immediately, purge history, rotate all derived credentials | Security owner |
| R-008 | Kubernetes, Rancher, or Helm chart versions are incompatible | Medium | High | CRDs fail, controllers crash, or support matrix mismatch | Pin versions and verify compatibility before bootstrap | Roll back to tested version set | Platform owner |
| R-009 | Backups exist but cannot restore | Medium | High | Restore test fails or recovery material is absent | Automate restore drill and checksum verification | Rebuild declarative state and document lost data class | Recovery owner |
| R-010 | Bonus work destabilizes core requirements | Medium | High | Core acceptance matrix is not green before bonus start | Core-first gate; bonuses isolated behind overlays | Remove GPU/Kueue/signing scope | Delivery owner |
| R-011 | Provider documentation differs from the installed schema | Medium | Medium | Plan rejects documented attributes | Export provider schema and pin lock file | Use verified schema and record documentation gap | IaC owner |
| R-012 | Assessor access is either insecure or too difficult | Medium | High | Access needs admin assistance or broad public ports | Least-privilege accounts, scripted checks, SSH tunnel fallback | Time-bounded ingress allowlist and guided session | Security owner |

## Review cadence

- Reassess before every phase gate.
- Add a risk when a workaround creates a new failure mode.
- Close a risk only with evidence; a documented limitation remains an accepted residual risk, not a closed risk.
