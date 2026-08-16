# Assignment Acceptance Matrix

This is the live requirement-to-proof source of truth. `Contracted` means the implementation and proof path are defined; it does not mean the capability exists. A row becomes `Verified` only after the automated test and sanitized live evidence both pass.

| ID | Requirement | Implementation contract | Automated verification | Required live evidence | Current state | Final exit condition |
|---|---|---|---|---|---|---|
| R01 | Verda CPU VMs with public IPs | Reusable Terraform modules with pinned IDs and protected lifecycle | Format, validate, plan, drift check | Sanitized instance inventory | Contracted; shape/image/location pinned | Reproducible apply and reachable hosts |
| R02 | Kubernetes | Three-node RKE2 cluster per implemented stage | Node, etcd, DNS, service, Cilium tests | `evidence/cluster/` transcripts | Contracted | Three Ready servers and healthy quorum |
| R03 | Rancher | HA replicas on `verda-mgmt`; manage both clusters in Stage B | API/UI health and cluster-state check | Scoped reviewer view | Contracted | Intended clusters Active; direct access retained |
| R04 | Argo CD | Pinned bootstrap, one root app, AppProjects, ApplicationSets | Sync/health and drift tests | Application inventory and drift recovery | Contracted | Git change reconciles automatically |
| R05 | Registry | Self-managed Harbor with Trivy | Push, scan API, digest and artifact checks | Artifact/scan/SBOM record | Contracted | Accepted artifact visible and immutable |
| R06 | Image security | SBOM, Cosign signature/provenance, digest admission policy | CI positive/negative policy tests | Signature, attestation, denial transcripts | Contracted | Unsigned/tag-only/external image rejected |
| R07 | Monitoring | kube-prometheus-stack per cluster; central Grafana | Target and query checks | Dashboard screenshots plus source JSON | Contracted | Required targets up and dashboards useful |
| R08 | Alerts | Small tested set of SLO/platform PrometheusRules | `promtool check/test rules` and fault test | Firing and resolved timeline | Contracted | Deliberate fault fires and later resolves |
| R09 | Logging | Loki on management; Alloy collectors | Canary and LogQL query test | Request-ID/time/version investigation | Contracted | Fault located through structured logs |
| R10 | Environments | `demo-dev`, `demo-staging`, `demo-prod` namespaces | Render and deployed-digest comparison | Environment inventory | Contracted | Same digest in all environments |
| R11 | Promotion | Git-reviewed dev → staging → prod digest changes | Promotion script and policy tests | PR/commit history | Contracted | Build once; promote without rebuild |
| R12 | RBAC | Scoped platform, developer, approver, reviewer, CI personas | `kubectl auth can-i` matrix | Expected denial transcript | Contracted | Developer cannot mutate prod/cluster scope |
| R13 | Network policy | Default deny plus explicit DNS/ingress/monitoring/app flows | Connectivity matrix | Hubble allowed/denied flows | Contracted | Cross-environment traffic blocked |
| R14 | Pod security | PSA plus Kyverno Audit → test → Enforce | Kyverno CLI and admission tests | Rejected privileged workload | Contracted | Noncompliant application pod rejected |
| R15 | Secrets | Sealed Secrets plus CI secret store | Secret scan and in-cluster decrypt test | Sanitized controller/recovery status | Contracted | No plaintext runtime secret in Git |
| R16 | Backup | RKE2, Velero, Longhorn and component-specific layers | Age/status/checksum checks | Off-cluster backup inventory | Contracted | Recent recovery points exist |
| R17 | Restore | Namespace/PVC restore with integrity fixture | Checksum and endpoint verification | Measured RTO/RPO report | Contracted | Data restored and verified |
| R18 | Cost | Actual compute/storage/object/traffic ledger | Recalculation and inventory reconciliation | `docs/cost.md` plus cost evidence | Phase 0 envelope verified; live spend pending | Actual/projected costs documented |
| R19 | Kueue bonus | CPU queues first; optional GPU flavor later | Queued/admitted/priority tests | Queue status and dashboard | Core-gated | Excess job queues before pod creation |
| R20 | AI-use log | Truthful assistant attribution and validation record | Documentation structure check | `docs/ai-usage.md` | Phase 0 and Phase 1 activity, corrections, and rejected approaches recorded | Inputs, corrections, and validation recorded |
| R21 | Access | TLS endpoints and least-privilege reviewer identities | Independent endpoint/login smoke test | Evaluator-permission transcript | Contracted | Evaluator reaches approved services |
| R22 | One-page summary | Evidence-aligned executive summary | Rendered page-count/content check | Final PDF/Markdown | Contracted | Exactly one page and factually aligned |

## Phase 0 traceability check

- All 22 blueprint requirements have an implementation, verification, evidence, and exit contract.
- No row is represented as implemented or live-tested in Phase 0.
- Account-dependent Phase 0 facts are evidence-backed; later live-resource facts remain explicitly gated rather than inferred.
- The immutable snapshot for this phase is `evidence/manifests/phase-0-acceptance-matrix.md`.

## Phase 1 repository-quality acceptance

| ID | Gate | Automated proof | State |
|---|---|---|---|
| Q01 | Canonical repository topology | `check_structure.py`: 115 directories and 185 required files | PASS |
| Q02 | Exact, reproducible tool delivery | Bootstrap plus 18 exact version assertions and cache provenance hashes | PASS |
| Q03 | Positive static quality pipeline | `make validate` across every applicable Phase 1 validator | PASS |
| Q04 | Kubernetes and custom-resource schemas | 12 valid resources across core, Argo CD, Kyverno, Kueue, Longhorn, Velero, Prometheus, and Sealed Secrets | PASS |
| Q05 | Invalid inputs are rejected | Terraform, Kubernetes, missing CRD schema, Prometheus, and private-key negative fixtures | PASS |
| Q06 | Developer hooks | Installed canonical hook and `pre-commit run --all-files` | PASS |
| Q07 | Repository and history secret scanning | Gitleaks working-tree and `--all` history scans with 100% redaction | PASS |
| Q08 | CI workflow | Actionlint plus local execution of the exact `make ci` workflow body; hosted run awaits a GitHub remote | PARTIAL |
| Q09 | Clean-clone bootstrap and validation | Final implementation clone at `f8364af`; zero copied caches; bootstrap and full CI parity passed | PASS |

Phase 1 cannot be marked fully complete until Q08 has a hosted successful run. This does not
authorize Phase 2.
