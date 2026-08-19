# Assignment Acceptance Matrix

This is the live requirement-to-proof source of truth. `Contracted` means the implementation and proof path are defined; it does not mean the capability exists. A row becomes `Verified` only after the automated test and sanitized live evidence both pass.

| ID | Requirement | Implementation contract | Automated verification | Required live evidence | Current state | Final exit condition |
|---|---|---|---|---|---|---|
| R01 | Verda CPU VMs with public IPs | Reusable Terraform modules with pinned IDs and protected lifecycle | Format, validate, plan, drift check | Sanitized instance inventory | PASS — 3 VMs, 3 unique endpoints, exact attachments, hostname-bound SSH, and zero drift verified | Reproducible apply and three uniquely reachable hosts |
| R02 | Kubernetes | Three-node RKE2 cluster per implemented stage | Node, etcd, DNS, service, Cilium tests | Curated Phase 4 cluster evidence | PASS for management cluster — 3 Ready schedulable servers, healthy quorum, Cilium, DNS, service, and policy paths | Three Ready servers and healthy quorum |
| R03 | Rancher | HA replicas on `verda-mgmt`; manage both clusters in Stage B | API/UI health and cluster-state check | Scoped reviewer view | Contracted | Intended clusters Active; direct access retained |
| R04 | Argo CD | Pinned bootstrap, one root app, AppProjects, ApplicationSets | Sync/health and drift tests | Application inventory and drift recovery | PASS — idempotent bootstrap, exact one-root/eight-child set, and 9/9 Healthy/Synced on protected `main` | Git change reconciles automatically |
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
| R16 | Backup | RKE2, Velero, Longhorn and component-specific layers | Age/status/checksum checks | Off-cluster backup inventory | PARTIAL — management etcd local and off-cluster snapshots live; later data layers remain contracted | Recent recovery points exist |
| R17 | Restore | Namespace/PVC restore with integrity fixture | Checksum and endpoint verification | Measured RTO/RPO report | Contracted | Data restored and verified |
| R18 | Cost | Actual compute/storage/object/traffic ledger | Recalculation and inventory reconciliation | `docs/cost.md` plus cost evidence | PASS through current Phase 5 work — no compute, volume, address, or key delta; known infrastructure remains $0.23165/hour | Actual/projected costs documented |
| R19 | Kueue bonus | CPU queues first; optional GPU flavor later | Queued/admitted/priority tests | Queue status and dashboard | Core-gated | Excess job queues before pod creation |
| R20 | AI-use log | Truthful assistant attribution and validation record | Documentation structure check | `docs/ai-usage.md` | Phase 0–5 implementation, debugging, delegation, and validation recorded | Inputs, corrections, and validation recorded |
| R21 | Access | TLS endpoints and least-privilege reviewer identities | Independent endpoint/login smoke test | Evaluator-permission transcript | PARTIAL — Argo TLS, anonymous denial, administrator login, and read-only reviewer pass on all three ingress addresses; later management UIs remain contracted | Evaluator reaches approved services |
| R22 | One-page summary | Evidence-aligned executive summary | Rendered page-count/content check | Final PDF/Markdown | Contracted | Exactly one page and factually aligned |

## Phase 0 traceability check

- All 22 blueprint requirements have an implementation, verification, evidence, and exit contract.
- No row is represented as implemented or live-tested in Phase 0.
- Account-dependent Phase 0 facts are evidence-backed; later live-resource facts remain explicitly gated rather than inferred.
- The immutable snapshot for this phase is `evidence/manifests/phase-0-acceptance-matrix.md`.

## Phase 1 repository-quality acceptance

| ID | Gate | Automated proof | State |
|---|---|---|---|
| Q01 | Canonical repository topology | `check_structure.py`: required directory/file contract with no unexplained root | PASS |
| Q02 | Exact, reproducible tool delivery | Bootstrap plus 18 exact version assertions and cache provenance hashes | PASS |
| Q03 | Positive static quality pipeline | `make validate` across every applicable Phase 1 validator | PASS |
| Q04 | Kubernetes and custom-resource schemas | 12 valid resources across core, Argo CD, Kyverno, Kueue, Longhorn, Velero, Prometheus, and Sealed Secrets | PASS |
| Q05 | Invalid inputs are rejected | Terraform, Kubernetes, missing CRD schema, Prometheus, and private-key negative fixtures | PASS |
| Q06 | Developer hooks | Installed canonical hook and `pre-commit run --all-files` | PASS |
| Q07 | Repository and history secret scanning | Gitleaks working-tree and `--all` history scans with 100% redaction | PASS |
| Q08 | CI workflow | Actionlint, locked-action parity, local `make ci`, and hosted run `31961790627` with retained reports | PASS |
| Q09 | Clean-clone bootstrap and validation | Fresh remote clone at `f4848cf`; zero copied `.local`; bootstrap and full CI parity passed with a clean worktree | PASS |
| Q10 | Repository governance | Real CODEOWNERS; protected `main`; app-bound required CI; PR, linear-history, no-force-push, no-deletion, conversation-resolution, secret-scanning, and push-protection controls verified through the GitHub API | PASS |

Phase 2 is complete. Its cloud-mutation targets remain closed; Phase 4 may reuse only the explicitly
allowlisted read-only/convergence prerequisites in `config/phase-map.json`.

## Phase 2 infrastructure acceptance

| ID | Gate | Automated/live proof | State |
|---|---|---|---|
| I01 | Exact Stage A resource boundary | Plan assertion plus live inventory: 3 instances, 3 OS volumes, 3 protected data volumes, and 1 registered SSH key | PASS |
| I02 | Independent host reachability | Three unique public endpoints and exact hostname over dedicated-key SSH | PASS |
| I03 | Persistent data lifecycle | `prevent_destroy`, bounded compute rollback, and preserved server-02 data volume through authorized compute recovery | PASS |
| I04 | State security and recoverability | DPAPI-sealed external state plus independently located encrypted backup and round-trip checks | PASS |
| I05 | Cost and drift | $0.23165/hour reconciled provider burn and zero-resource final Terraform plan | PASS |
| I06 | Final protected-main CI | Commit `4d05890fa22edd126ff25df195bf93e2e3cf33eb`, run `32012648406`, job `95335349495` | PASS |

## Phase 3 host and secure-network acceptance

| ID | Gate | Automated/live proof | State |
|---|---|---|---|
| H01 | Immutable operating-system baseline | Ubuntu 24.04 Minimal, x86_64, cgroup v2, kernel/storage prerequisites, time, locale, swap, and service assertions on all hosts | PASS |
| H02 | Safe administrative transition | Fresh pinned-key `platform-admin` session and sudo before root/password disable; timed rollback; independent positive/negative probes | PASS |
| H03 | Persistent storage preparation | Exact stable attachment, complete empty-media proof before first format, ext4/UUID mount, ownership/free-space, reboot persistence | PASS |
| H04 | Encrypted internal addressing | Node-local private keys, fixed overlay addresses, 1420 MTU, 6/6 no-fragment paths, recent handshakes, sustained ring traffic | PASS |
| H05 | Public firewall boundary | SSH only from approved `/32`; peer-only WireGuard; HTTP/S, API, supervisor, etcd, kubelet, metrics, and sampled NodePorts denied | PASS |
| H06 | Idempotency | Two complete prepare/network/diagnostic passes and post-reboot convergence report `changed=0` on all hosts | PASS |
| H07 | Reboot survival | Three serial reboots prove new boot identities, cloud-init settlement, strict access, mounts, mesh, firewall, and time | PASS |
| H08 | Phase isolation at closure | Zero cloud actions; RKE2 binary/config/data absent; Phase 4 remained blocked until explicit authorization | PASS |
| H09 | Final merged hosted CI | Commit `f9ce3e266845d460faa5ac93b7bba2989995f600`, run `32042890480`, job `95425241122`; bootstrap, complete suite, and report upload passed | PASS |

Phase 3 is complete and Phase 4 is explicitly authorized. Rancher, Argo CD, Harbor, DNS, Stage A
platform services, Stage B, and every Phase 5+ action remain prohibited.

## Phase 4 management-cluster acceptance

| ID | Gate | Automated/live proof | State |
|---|---|---|---|
| K01 | Exact supported RKE2 path | Official compatibility/release evidence, immutable artifact checksums, exact role variables | PASS |
| K02 | Immutable network design | Pairwise CIDR test plus live controller and node-route comparison before start | PASS — 30 observed routes, 9 owned resume routes, zero overlaps, no raw routes recorded |
| K03 | Secure idempotent bootstrap | Prepare/start separation, process-only token, encrypted recovery copy, serial health gates, parity hash | PASS — definitive bootstrap and zero-change active-cluster replay on all three servers |
| K04 | CIS and control-plane hardening | `profile: cis`, generated sysctls, audit policy, encryption, focused self-assessment | PASS — 10/10 focused checks on each server; manual identity exceptions documented |
| K05 | Cilium and Traefik | Conservative supported configs, 1370 MTU, Hubble/metrics, internal multi-node Traefik | PASS — full connectivity and internal three-node Traefik smoke green |
| K06 | Three-node cluster health | Nodes, API, system pods, etcd, DNS/service, Cilium, traffic, policy, MTU, cleanup | PASS — three Ready schedulable servers and all listed core checks green |
| K07 | External firewall boundary | Approved-source API plus negative supervisor/etcd/kubelet/Cilium/metrics/NodePort scan | PASS — all three nodes; independent non-allowlisted vantage remains a limitation |
| K08 | Local and off-cluster snapshots | Scheduled/on-demand snapshot and both local/S3 listings | PASS — compressed ready recovery point in both location classes; 6-hour schedule and 8+8 retention |
| K09 | Single-node and endpoint failure | Non-primary stop/recovery, then primary endpoint loss/direct path/quorum/recovery | PASS — definitive bootstrap and corrected-current-tree independent verification both exercised the restart-history-preserving path |
| K10 | Sanitized diagnostics and quality | Support-bundle exclusions plus complete local `make ci` | PASS — live bundle, local quality, PR, and protected-main hosted CI pass |

Overall Phase 4 state is **PASS**. The definitive bootstrap, corrected-current-tree independent
verification, final local quality, PR run `32275331008`, and protected-main run `32275537006` all
passed. Phase 5 is authorized and starts with its own read-only preflight.

## Phase 5 storage, TLS, and GitOps-bootstrap acceptance

| ID | Gate | Automated/live proof | State |
|---|---|---|---|
| P01 | Minimal bootstrap boundary | Pinned Argo release plus one root Application; idempotent replay at Helm revision 5 | PASS |
| P02 | GitOps ownership | Exact one-root/eight-child set; all nine Applications Healthy and Synced | PASS |
| P03 | Certificate lifecycle | Staging-first admission, then production; six cert-manager replicas and two certificates/issuers Ready | PASS |
| P04 | Durable storage | Three dedicated disks; critical 4 MiB checksum preserved across reschedule; replicas 3/3 and cleanup absent | PASS |
| P05 | Authenticated ingress | TLS through three addresses, anonymous denied, admin authenticated, reviewer read-only | PASS |
| P06 | Direct recovery access | Protected mode-`0600` direct kubeconfig works independently of public ingress and Rancher | PASS |
| P07 | External boundary | HTTPS 200, non-ACME HTTP 404, four allowed and 28 denied TCP classes on each node | PASS |
| P08 | Post-install capacity | +0.065 CPU cores and +16.830 GiB memory after equal-node loss; worst-two-node storage remains positive | PASS for Phase 5; Phase 6 not admitted |
| P09 | Final current-tree local quality | Complete credential-free `make ci` after evidence curation | PASS |
| P10 | Hosted closeout quality | Reviewed PR and protected-main workflow | PENDING |

Overall Phase 5 state is **PARTIAL** solely because P10 remains pending. All live exit gates and P09
pass. Phase 6 remains prohibited until the hosted closeout merges.
