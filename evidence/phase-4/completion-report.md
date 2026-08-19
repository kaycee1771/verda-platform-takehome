# Phase 4 completion report

## Status

PASS

## Implemented

- Cluster automation: `infra/ansible/playbooks/install-rke2.yml`,
  `infra/ansible/playbooks/remove-rke2.yml`,
  `infra/ansible/playbooks/configure-etcd-backup.yml`,
  `infra/ansible/inventories/group_vars/management_servers.yml`,
  `infra/ansible/roles/rke2_server/`, `infra/ansible/roles/etcd_backup/`,
  `infra/ansible/roles/firewall/templates/90-verda-platform.nft.j2`, and
  `infra/ansible/roles/diagnostics/tasks/main.yml`.
- Guarded controller and verification surface: `scripts/cluster/`,
  `scripts/collect-rke2-diagnostics.sh`, `scripts/verify-cluster.sh`,
  `tests/cluster/phase4/network-smoke.yaml`, and
  `tests/static/test_phase4_contract.py`.
- Repository quality and evidence safety: `schemas/schema-sources.lock.yaml`,
  `scripts/quality/validate.sh`, `scripts/quality/secret-scan.sh`,
  `tests/static/test_phase4_evidence_safety.py`,
  `tests/static/test_secret_scan_contract.py`, and
  `tests/static/repository-contract.yaml`.
- Status and operating records: `README.md`, `SUMMARY.md`,
  `IMPLEMENTATION_STATUS.md`, `CHANGELOG.md`, `versions.lock.yaml`,
  `docs/acceptance-matrix.md`, `docs/access.md`,
  `docs/ai-usage.md`, `docs/architecture.md`, `docs/cost.md`,
  `docs/known-limitations.md`, `docs/operations-model.md`, and
  `docs/risk-register.md`.
- Live resources: the existing three management VMs and six block volumes
  were converged into a three-server RKE2/etcd cluster. One manually managed
  object-storage bucket and one bounded access credential were added under the
  documented provider-gap exception. No compute, block-volume, public-address,
  or SSH-key resource was added, removed, or resized.

## Decisions and tradeoffs

- Amended `docs/adr/0001-rke2.md` for the implemented pinned RKE2 topology.
- Amended `docs/adr/0005-network-endpoints.md` for the named default endpoint,
  direct-node recovery paths, deterministic resolver override, and retained
  primary-endpoint SPOF.
- Amended `docs/adr/0011-backup-recovery.md` for the proven local/off-cluster
  RKE2 snapshot target while retaining the later restore/checksum gate.
- Retained the accepted public-endpoint plus WireGuard Path B, the exact three
  schedulable-server topology, bundled RKE2 components, and explicit endpoint
  limitation.
- Used a manual object-storage lifecycle because provider `1.1.2` exposes
  neither bucket nor object-storage credential resources; the boundary remains
  revocable and auditable.
- Ran every distinct official Cilium functional scenario unfiltered and fatal,
  plus a separate strict localhost-Hubble pod-to-pod canary. This avoids
  source-proven v0.19.7 matcher defects while retaining strict observation proof
  and zero lost-event delta for the canary.
- Preserved explained restart history after controlled node loss instead of
  deleting healthy pods. The stability gate then required identities and
  regular/init restart counts to remain unchanged.

## Verification performed

- `make cluster-bootstrap`: guarded bootstrap, common-config convergence,
  RKE2/etcd installation, snapshots, firewall, connectivity, failure drills,
  support-bundle checks, stability, and active cluster idempotency completed.
- `make verify-cluster`: corrected-current-tree independent cycle exited `0` with
  `[PASS] Phase 4 verification cycle completed.`
- Live summaries: three Ready schedulable servers; three etcd members and one
  leader; zero alarms; full functional Cilium suite PASS; strict Hubble canary
  PASS with zero positive lost-event deltas; network smoke, focused CIS,
  snapshots, public boundary, both one-node drills, support sanitization, and
  270-second stability PASS.
- `make ci`: PASS on the final documentation-complete candidate; 90 tests,
  six negative fixtures, every pre-commit hook, and both Gitleaks scopes passed.
- Hosted `Credential-free quality gates`: PASS on PR run `32275331008`, job
  `96141296537`, and protected-main run `32275537006`, job `96141963292`.

## Evidence created

- Index and gates: `evidence/phase-4/README.md`,
  `evidence/phase-4/exit-gates.md`.
- Selection/preflight: `evidence/phase-4/version-selection.md`,
  `evidence/phase-4/cidr-design.md`, `evidence/phase-4/live-preflight.md`,
  `evidence/phase-4/object-storage-boundary.md`,
  `evidence/phase-4/manual-object-storage-exception.md`.
- Installation/health: `evidence/phase-4/management-installation.md`,
  `evidence/phase-4/common-config-parity.md`,
  `evidence/phase-4/management-nodes.txt`,
  `evidence/phase-4/management-etcd-health.txt`,
  `evidence/phase-4/management-cilium-connectivity.txt`,
  `evidence/phase-4/management-networking.md`.
- Security/recovery: `evidence/phase-4/management-firewall-scan.md`,
  `evidence/phase-4/management-cis-assessment.md`,
  `evidence/phase-4/management-snapshots.md`,
  `evidence/phase-4/management-node-failure.md`,
  `evidence/phase-4/management-endpoint-failure.md`,
  `evidence/phase-4/management-support-bundle.md`,
  `evidence/phase-4/stability-and-idempotency.md`.
- Closeout: `evidence/phase-4/deviations-and-recovery.md`,
  `evidence/phase-4/independent-verification.md`,
  `evidence/phase-4/repository-validation.md`,
  `evidence/phase-4/hosted-ci.md`, and this report.
- Raw logs, JSON reports, support archives, kubeconfigs, endpoint values, and
  protected runtime material remain ignored or external and are not evidence
  artifacts.

## Deviations or failures

- Initial Cilium L7 traffic failed closed because the host input hook dropped
  precisely marked proxy traffic. A narrowly scoped proxy-mark/source/interface
  rule corrected it without a broad forwarding or public-ingress allowance.
- The RKE2 snapshot secret required an endpoint authority rather than a full
  URL; TLS remained enabled after correction.
- Pinned Cilium CLI v0.19.7 strict matchers incorrectly model numeric
  ClusterIP/KPR-false replies and a non-L7 FQDN policy. Complete functional
  coverage therefore remains fatal without its telescope, while a separate
  source-audited strict Hubble canary proves observation.
- The first post-drill controller design would have erased expected restart
  history. It was replaced by bounded full-stack readiness followed by
  unchanged-identity/restart stability measurement.
- A genuinely independent non-allowlisted external scan vantage was not
  available. All allowlisted and deny-boundary checks from the controller were
  executed and the limitation remains explicit.
- No unresolved Phase 4 failure remains. Later restore, second-vantage, and
  manual object-lifecycle limitations retain their owning future gates.

## Security and secrets check

- PASS — no credential, token, private key, kubeconfig, certificate material,
  endpoint value, protected identifier, or raw support archive was committed or
  printed in curated output.
- PASS — runtime credentials and recovery material stayed outside Git;
  evidence contains only allowlisted assertions and bounded scalars.
- PASS — the retained support artifact passed exact topology, size, type,
  metadata, trailing-data, redaction, and exact protected-value absence checks;
  the remote copy was removed.

## Cost impact

- Added: one manually managed object-storage bucket and one bounded access
  credential outside the provider `1.1.2` resource model; a positive-size
  compressed recovery point is retained there.
- Added/removed for compute, block volume, public address, and SSH key: none.
- Known infrastructure rate: `$0.23165/hour` and `$5.55948/day` at the
  authenticated 2026-08-19 13:37Z reconciliation.
- Total rate: `$5.55948/day` plus unmeasured object-storage capacity/operations
  charges. The latter is not claimed as zero and remains within the approved
  `$5` unquoted-services allowance; exact capacity/operations reconciliation
  remains a Phase 14 obligation.

## Exit-gate result

- PASS — pinned version and artifact provenance.
- PASS — CIDR design, route-overlap, and live preflight.
- PASS — three-node common configuration, installation, readiness, and
  schedulability.
- PASS — three-member etcd health, leadership, alarms, latency, snapshots, and
  retention.
- PASS — Cilium/Hubble readiness, complete functional connectivity, strict
  observation canary, and zero canary-window lost-event delta.
- PASS — same-node/cross-node, ClusterIP, DNS, egress, deny policy, internal
  Traefik, and MTU smoke.
- PASS — focused CIS assessment and encrypted/audited control-plane posture.
- PASS — allowlisted public API and denial of public service, NodePort, Cilium,
  and internal ports.
- PASS — genuine non-primary and designated-primary one-node loss, quorum
  survival, direct recovery path, full recovery, and explicit omission of
  two-node loss.
- PASS — bounded sanitized support bundle, active-cluster idempotency, and
  270-second stability.
- PASS — corrected-current-tree independent live verification.
- PASS — final complete local `make ci` after this report edit.
- PASS — hosted `Credential-free quality gates` on the reviewed Phase 4 commit
  and protected `main`.
- PASS — overall Phase 4.

## Next phase

- Phase 5 — Storage, ingress, certificates, and bootstrap boundary. The master
  directive authorizes it; the protected Phase 4 baseline is complete. Phase 5
  starts with its own read-only prerequisite and rollback gate.
