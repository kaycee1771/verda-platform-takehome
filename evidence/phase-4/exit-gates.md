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
| Final hosted CI | PASS | `hosted-ci.md` |

Overall Phase 4 result: **PASS**. All live gates, corrected-current-tree independent verification,
final local quality, PR validation, and protected-main hosted CI are green. Phase 5 is authorized
and begins with its own read-only prerequisite gate.
