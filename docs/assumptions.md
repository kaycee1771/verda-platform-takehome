# Assumption Register

High-impact assumptions must be validated before the phase they block. Unknowns are not silently converted into architecture facts.

| ID | Assumption | Impact if false | Validation | Gate | State |
|---|---|---|---|---|---|
| A-001 | The assignment coupon provides enough credit for three CPU VMs and persistent storage during the review window | Topology must be resized or shortened | Redeem coupon and capture balance without recording the code | GATE-004 | Open |
| A-002 | Verda API credentials can be created and provided through environment variables | Automated discovery and Terraform cannot proceed | Run `verda doctor` and credential-presence check | GATE-001 | Open |
| A-003 | A CPU flavor with sufficient memory is available in one location | Platform components may be unschedulable | Capture `verda instance-types --cpu` and availability | GATE-002 | Open |
| A-004 | Three VMs can communicate over stable peer addresses | RKE2 quorum and storage replication fail | Verify private/public addressing and peer port connectivity | GATE-003 | Open |
| A-005 | One persistent NVMe volume can be attached to each VM | Longhorn data placement must use OS disks or another design | Capture volume types and provider schema | GATE-002 | Open |
| A-006 | Verda object-storage credentials and a compatible endpoint are available | Backups and Loki need another target | Run read-only object-storage status and a later non-production compatibility test | GATE-002 | Open |
| A-007 | A controllable DNS domain is available | Use an assessor-friendly temporary DNS alternative and document limitations | Select domain strategy before ingress implementation | GATE-003 | Open |
| A-008 | The Git host supports protected branches and encrypted CI secrets | Promotion approvals and robot credentials need another workflow | Select Git remote and inspect repository controls | GATE-005 | Open |
| A-009 | Namespace-isolated environments satisfy the take-home requirement | More clusters may be required | State the tradeoff in ADR 0002 and show the production target | None | Accepted |
| A-010 | Assessors can receive credentials through a channel separate from the public repository | Public access may be unsafe or unusable | Agree on delivery and expiry process | GATE-005 | Open |
| A-011 | The platform contains only demonstration data | Stronger privacy controls may be required | Keep sample data synthetic and document it | None | Accepted |
| A-012 | Core functionality takes priority over GPU and Kueue bonuses | Bonus scope may be reduced | Enforce requirement gates and the core-first rule | None | Accepted |

## Validation rule

An open assumption with high availability, security, cost, or data-loss impact cannot cross its blocking gate. Its contingency must be selected in an ADR before implementation continues.
