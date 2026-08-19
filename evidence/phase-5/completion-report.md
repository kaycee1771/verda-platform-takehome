# Phase 5 completion report

## Status

PARTIAL

All live Phase 5 exit gates and final current-tree local CI pass. Hosted closeout
CI remains pending, so overall PASS is not yet claimed.

## Implemented

- Bootstrap boundary: `bootstrap/argocd/` and `scripts/bootstrap-gitops.sh` install
  the pinned Argo CD chart, establish exact CRDs, apply one root Application,
  rotate accounts, and write protected external sessions.
- GitOps ownership: `gitops/appprojects/platform.yaml` and the exact Applications
  under `gitops/root/` own project policy, cert-manager, Longhorn, certificates,
  and authenticated Argo ingress.
- Certificate and ingress desired state:
  `platform/management/cert-manager/{controller-values.yaml,staging/,production/}`
  and `platform/management/ingress/argocd/` implement staging-first production TLS
  through RKE2-owned Traefik.
- Storage desired state: `platform/management/longhorn/{values.yaml,prerequisites/,resources/}`
  configures three dedicated disks and critical three-replica storage classes.
- Runtime proof: `scripts/phase5/capacity-report.py`,
  `scripts/phase5/longhorn-capacity.py`,
  `scripts/phase5/longhorn-storage-contract.py`,
  `scripts/phase5/longhorn-storage-test.sh`,
  `scripts/phase5/verify-argocd-ingress.py`, and
  `scripts/phase5/verify-runtime.sh` enforce capacity, integrity, TLS, RBAC,
  application-set, and external-boundary gates.
- Network boundary: `config/firewall-port-matrix.yaml`,
  `infra/ansible/inventories/group_vars/management_servers.yml`, and
  `infra/ansible/roles/firewall/templates/90-verda-platform.nft.j2` admit only the
  contracted Phase 5 public classes.
- Offline validation: `schemas/schema-sources.lock.yaml`,
  `scripts/quality/{bootstrap_charts.py,bootstrap_schemas.py,validate.sh}`, the
  Phase 5 tests under `tests/static/`, `tests/static/repository-contract.yaml`, and
  `versions.lock.yaml` pin and test the complete desired state.
- Closeout surfaces: `README.md`, `IMPLEMENTATION_STATUS.md`, `SUMMARY.md`,
  `CHANGELOG.md`, current documents under `docs/`, and curated Markdown under
  `evidence/phase-5/`.

## Decisions and tradeoffs

- Retained RKE2-owned Traefik instead of adding a second ingress controller.
- Retained the accepted `sslip.io` HTTP-01 boundary because no custom domain was
  selected; plain HTTP is limited to ACME solver behavior.
- Kept three replicas for critical Longhorn data despite the raw-capacity cost.
- Kept direct mode-`0600` kubeconfig access independent of future Rancher.
- Amended `docs/adr/0006-storage.md` with the live three-disk/reschedule result
  while preserving the Phase 13 off-cluster recovery gate.
- Amended `docs/adr/0007-gitops.md` with the exact two-action bootstrap, live
  Application topology, staged TLS promotion, and ingress-lifecycle ownership.

## Verification performed

- `make bootstrap-gitops CLUSTER=management`: definitive replay PASS at Helm
  revision 5; root Healthy and Synced; protected sessions refreshed.
- `CONFIRM_DESTRUCTIVE_ACTION=yes scripts/phase5/longhorn-storage-test.sh --confirm`:
  bounded critical-volume drill PASS with checksum, identity, replica, and cleanup
  assertions.
- `scripts/phase5/verify-runtime.sh` with protected external input files: PASS for
  Applications, certificates, TLS, authentication, RBAC, HTTP behavior, capacity,
  and the external boundary.
- Exact Application inventory: 9/9 Healthy and 9/9 Synced, comprising one root
  and eight children.
- cert-manager readiness: six required replicas ready; two certificates and two
  issuers Ready with exact references.
- Longhorn critical reschedule: 4 MiB checksum and storage identities preserved,
  replicas 3/3 healthy, and cleanup absence proven.
- Capacity: 5.935 CPU cores requested with +0.065 one-node-loss headroom;
  9.428 GiB memory requested with +16.830 GiB headroom; 314887372800 bytes
  available and 209924915200 bytes in the worst two-node view.
- TLS and access: three ingress addresses passed hostname/issuer/date inspection;
  anonymous access denied; reviewer read allowed and sync/action denied.
- Endpoint behavior: HTTPS 200 and non-ACME HTTP 404 on all three addresses.
- External scan: four allowed and 28 denied TCP port classes on each of three
  nodes.
- `python scripts/quality/check_structure.py`: 118 directories and 339 required
  files PASS.
- `python -m unittest discover -s tests/static -p 'test_phase5*.py'`: 80 focused
  Phase 5 tests PASS, including eight evidence-safety cases.
- `pymarkdown --config .pymarkdown.json scan ...`: all changed Markdown PASS.
- `bash scripts/quality/secret-scan.sh --working-tree-only`: PASS with 100 percent
  redaction.
- `git diff --check`: PASS.
- Protected-main baseline validation: commit `adc0a071`, run `32299258822`, job
  `96217807991` PASS. This predates final evidence curation and is not the closeout
  hosted gate.
- Final current-tree local CI: PASS — 175 static/behavioral tests and every
  canonical offline gate passed.
- Hosted closeout CI: PENDING.

## Evidence created

- `evidence/phase-5/versions-and-compatibility.md`
- `evidence/phase-5/preflight-cluster-health.md`
- `evidence/phase-5/gitops-bootstrap.md`
- `evidence/phase-5/longhorn-reschedule.md`
- `evidence/phase-5/tls-access-and-boundary.md`
- `evidence/phase-5/capacity-before-after.md`
- `evidence/phase-5/repository-validation.md`
- `evidence/phase-5/hosted-ci.md`
- `evidence/phase-5/exit-gates.md`
- `evidence/phase-5/README.md`
- `evidence/phase-5/completion-report.md`

## Deviations or failures

- Phase 5 is not yet closed because hosted closeout CI has not completed and merged.
- The public hostname uses the accepted `sslip.io` design rather than a custom
  domain. This is deliberate and does not weaken TLS or authentication.
- Longhorn replication is not represented as off-cluster backup or application-
  consistent restore; that proof remains deferred to Phase 13.
- Protected repair PRs #8–#17 closed observed fail-closed gaps without changing the
  accepted architecture: #8 established exact Argo CRDs before atomic install; #9
  bounded generated passwords to Argo's contract; #10 aligned Longhorn live
  capture; #11 aligned ext-family status with independent ext4 proof; #12 promoted
  production certificates only after staging; #13 exposed Argo only after TLS and
  authentication; #14 delegated ingress health to explicit external proof; #15
  scoped RBAC checks to exact project/application objects; #16 restored positive
  one-node-loss CPU headroom without reducing replicas; and #17 enforced the exact
  zero-ingress-to-Git-owned-ingress lifecycle.

## Security and secrets check

- No secret was committed or printed.
- No credential, session value, kubeconfig, endpoint address, certificate body,
  checksum value, Kubernetes identity, raw live payload, or command log is included.
- Protected files remained external, non-symlink, operator-owned, and mode `0600`.
- Evidence contains only fixed labels, public source metadata, commit identity,
  and sanitized aggregate scalars.

## Cost impact

- Verda billable-resource delta: zero compute instances, zero volumes, zero public
  addresses, zero registered keys, and zero object-storage resources added or
  removed.
- In-cluster delta: pinned Argo CD, cert-manager, Longhorn, Certificate/Issuer,
  StorageClass, AppProject/Application, and Argo Ingress resources on the existing
  management cluster. These consume existing capacity but add no separately
  quoted Verda resource.
- Temporary drill delta: the 4 MiB integrity workload and its Kubernetes/Longhorn
  objects were removed; cleanup absence passed.
- Known infrastructure rate remains `$0.23165/hour` or `$5.55948/day`.
- Object-storage positive-size capacity/request cost remains unmeasured, is not
  represented as zero, and stays within the existing `$5` unquoted-services
  allowance pending Phase 14 reconciliation.

## Exit-gate result

- Argo owns day-one desired state: PASS.
- Persistent storage reschedule and integrity: PASS.
- TLS across every ingress address: PASS.
- Authenticated management access and read-only reviewer: PASS.
- Rancher-independent break-glass access: PASS.
- Positive post-install capacity margin: PASS for Phase 5.
- Final current-tree local CI: PASS.
- Protected hosted closeout CI: PENDING.

## Next phase

The only immediate work is Phase 5 closeout: publish through protected review and
record hosted CI. After that closeout is merged, Phase 6 may
begin under the existing continuous Phases 5–17 directive and its own fail-closed
prerequisites. The phase map remains active at Phase 5 until the merge.
