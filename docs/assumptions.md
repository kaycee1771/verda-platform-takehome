# Assumption Register

High-impact assumptions must be validated before the phase they block. Unknowns are not silently converted into architecture facts.

| ID | Assumption | Impact if false | Validation | Gate | State |
|---|---|---|---|---|---|
| A-001 | The assignment coupon funds Stage A for seven days | Topology must be resized or shortened | Authenticated balance and current-rate capture plus cost envelope | GATE-001/GATE-004 | Verified: $50.51 envelope vs $115.67 balance |
| A-002 | Verda Cloud API credentials can be supplied through environment variables | Terraform cannot proceed | Official auth docs/schema; create/test credentials outside Git | GATE-006 before Phase 2 | Verified with a time-bound, process-only project credential; values never persisted |
| A-003 | A CPU flavor with sufficient memory is available in one location | Platform components may be unschedulable | Authenticated current-account catalog/availability | GATE-002 | Verified: `CPU.4V.16G` in FIN-01/02/03 |
| A-004 | Three VMs can communicate over stable public peer addresses | RKE2 quorum and storage replication fail | Provider/public-IP evidence now; live WireGuard/MTU/port tests after apply | GATE-007 before Phase 3 | Partially verified; Path B selected |
| A-005 | One persistent NVMe data volume can be attached to each VM | Longhorn needs another device strategy | Schema, console catalog/locations/single-attach behavior, then live attachment/reboot test | Phase 2 exit | Attachment and compute-replacement preservation verified; filesystem/reboot behavior remains Phase 3 |
| A-006 | Verda object-storage credentials and a compatible endpoint are available | Backups and Loki need another target | Current Credentials page, CLI status, then entitlement/S3 compatibility test | GATE-008 before Phase 5 | Not currently surfaced; fallback required if unchanged |
| A-007 | A controllable DNS domain is available | Use an assessor-friendly temporary alternative | User selected no custom domain; `sslip.io` fallback documented | GATE-005 | Fallback accepted |
| A-008 | The Git host supports protected branches and encrypted CI secrets | Promotion approvals and robot credentials need another workflow | Select Git remote and inspect repository controls | Phase 10 gate | GitHub protection verified in Phase 1; future CI-secret use remains separately gated |
| A-009 | Namespace-isolated environments satisfy the take-home requirement | More clusters may be required | State tradeoff in ADR-0002 and show production target | None | Accepted |
| A-010 | Assessors can receive credentials through a channel separate from the public repository | Public access may be unsafe or unusable | Agree on delivery and expiry process | Phase 17 gate | Open |
| A-011 | The platform contains only demonstration data | Stronger privacy controls may be required | Keep sample data synthetic and document it | None | Accepted |
| A-012 | Core functionality takes priority over GPU and Kueue bonuses | Bonus scope may be reduced | Enforce requirement gates and core-first rule | None | Accepted |
| A-013 | Provider resource absence means this provider cannot automate a capability, not that every Verda offering lacks it | A valid alternate surface could be incorrectly rejected | Correlate exact schema, CLI 1.8.1, and current project console | GATE-003 | Verified for current self-service surfaces; universal claim avoided |
| A-014 | Stage B remains affordable after Stage A | Gold topology may remain designed-only | Recalculate remaining credit/time only after Stage A evidence is green | Stage B gate | Planning scenario $36.51 incremental; still unverified |

## Validation rule

An open assumption with high availability, security, cost, or data-loss impact cannot cross its blocking gate. Its contingency must be selected in an ADR before implementation continues.
