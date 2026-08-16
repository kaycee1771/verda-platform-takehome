# Assumption Register

High-impact assumptions must be validated before the phase they block. Unknowns are not silently converted into architecture facts.

| ID | Assumption | Impact if false | Validation | Gate | State |
|---|---|---|---|---|---|
| A-001 | The assignment coupon provides enough credit for three CPU VMs and persistent storage during the review window | Topology must be resized or shortened | Confirm coupon and capture balance without recording the code | GATE-001/GATE-004 | Blocked: unauthenticated |
| A-002 | Verda API credentials can be supplied through environment variables | Automated discovery and Terraform cannot proceed | `verda doctor`, credential booleans, and authenticated list calls | GATE-001 | Blocked: variables/profile absent |
| A-003 | A CPU flavor with sufficient memory is available in one location | Platform components may be unschedulable | Capture `verda instance-types --cpu` and availability | GATE-002 | Blocked: unauthenticated |
| A-004 | Three VMs can communicate over stable peer addresses | RKE2 quorum and storage replication fail | Inspect account network features, then test peer paths before RKE2 | GATE-003 | Unverified |
| A-005 | One persistent NVMe volume can be attached to each VM | Longhorn data placement must use OS disks or another design | Provider 1.1.2 schema confirms volume/attachment resources; account type/size/price still required | GATE-002 | Partially verified |
| A-006 | Verda object-storage credentials and a compatible endpoint are available | Backups and Loki need another target | Official docs confirm separate S3 credentials; run read-only status and later compatibility test | GATE-002 | Partially verified; access untested |
| A-007 | A controllable DNS domain is available | Use an assessor-friendly temporary DNS alternative and document limitations | Candidate domain or documented `sslip.io` fallback | GATE-005 | Fallback accepted |
| A-008 | The Git host supports protected branches and encrypted CI secrets | Promotion approvals and robot credentials need another workflow | Select Git remote and inspect repository controls | Phase 10 gate | Open |
| A-009 | Namespace-isolated environments satisfy the take-home requirement | More clusters may be required | State the tradeoff in ADR 0002 and show the production target | None | Accepted |
| A-010 | Assessors can receive credentials through a channel separate from the public repository | Public access may be unsafe or unusable | Agree on delivery and expiry process | Phase 17 gate | Open |
| A-011 | The platform contains only demonstration data | Stronger privacy controls may be required | Keep sample data synthetic and document it | None | Accepted |
| A-012 | Core functionality takes priority over GPU and Kueue bonuses | Bonus scope may be reduced | Enforce requirement gates and the core-first rule | None | Accepted |
| A-013 | Provider resource absence means the capability cannot be automated by this provider, not that the Verda account lacks it | A valid console/API feature could be incorrectly rejected | Inspect the exact 1.1.2 schema and authenticated account/API/console separately | GATE-003 | Accepted |
| A-014 | Stage B is affordable and achievable after Stage A | Gold topology may remain designed-only | Recalculate remaining credit/time only after Stage A evidence is green | Stage B gate | Unverified |

## Validation rule

An open assumption with high availability, security, cost, or data-loss impact cannot cross its blocking gate. Its contingency must be selected in an ADR before implementation continues.
