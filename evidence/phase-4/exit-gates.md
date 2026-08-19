# Phase 4 Exit Gates

| Exit gate | Result | Evidence or blocker |
|---|---|---|
| Exact supported version path and immutable artifacts | PASS | `version-selection.md` |
| Non-overlapping immutable CIDR design | PASS | `cidr-design.md` |
| Live predecessor boundary and zero cloud drift | PASS | `live-preflight.md` |
| Staged installation and common-config parity | PASS | `management-installation.md`; `common-config-parity.md` |
| Three Ready nodes and healthy API/system pods | PASS | `management-nodes.txt` |
| etcd health, leader, alarms, database, and disk behavior | PASS | `management-etcd-health.txt` |
| Cilium, Hubble, DNS/service, policy, Traefik, and MTU | PASS | `management-cilium-connectivity.txt`; `management-networking.md` |
| Focused CIS and audit/secrets-encryption controls | PASS | `management-cis-assessment.md` |
| Local and off-cluster etcd snapshot | PASS | `management-snapshots.md`; `manual-object-storage-exception.md` |
| Final external firewall scan | PASS | `management-firewall-scan.md` |
| Non-primary and primary-endpoint failure tests | PASS | `management-node-failure.md`; `management-endpoint-failure.md` |
| Sanitized support bundle | PASS | `management-support-bundle.md` |
| Stability and active-cluster idempotency | PASS | `stability-and-idempotency.md` |
| Independent current-tree verification | PASS | `independent-verification.md` |
| Final complete local quality suite | PASS | `repository-validation.md` |
| Final hosted CI | PENDING | Requires explicit publication authorization |

Overall Phase 4 result: **PARTIAL / IN PROGRESS**. All live gates, including the corrected
current-tree independent verification and final local quality, are green. No overall PASS is
claimed until hosted CI is proven. Phase 5 live mutation remains prohibited before that protected
baseline.
