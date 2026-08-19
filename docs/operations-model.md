# Platform Operations and Source-of-Truth Model

## Ownership matrix

| Layer | Authoritative owner | Permitted responsibilities | Prohibited overlap |
|---|---|---|---|
| Verda infrastructure | Terraform | SSH-key registration, CPU/GPU instances, attached block volumes, startup scripts, stable metadata/outputs; object storage only if a verified provider resource exists | Ansible and console do not create or resize infrastructure during normal operation |
| Host and RKE2 | Ansible | OS preparation, hardening, firewall, private/WireGuard networking, filesystems, RKE2 install/configuration, snapshot configuration, sanitized bootstrap outputs | Terraform does not manage mutable host configuration; ad-hoc SSH is not desired state |
| Bootstrap | Minimal pinned scripts | Install Argo CD once, apply one root Application, perform unavoidable initial cluster registration | Bootstrap does not install the rest of the platform |
| In-cluster desired state | Argo CD | Namespaces, certificates, Rancher, Longhorn, Harbor, observability, policy, Velero, Kueue, and applications | Terraform/CI do not deploy Helm releases directly after bootstrap |
| Artifact production | CI | Test, build once, SBOM, vulnerability gate, push, digest resolution, signing/provenance, dev promotion PR | CI does not deploy directly to Kubernetes |
| Desired state and audit | Git | Platform/application state, policies, ADRs, runbooks, non-secret config, promotion history, evidence metadata | Git never stores plaintext credentials or recovery keys |

## Change paths

1. Infrastructure changes: reviewed Terraform plan, explicit apply, then generated Ansible inventory.
2. Host/RKE2 changes: reviewed Ansible changes, canary/serial convergence, idempotency verification.
3. Platform changes: reviewed Git change, Argo CD reconciliation, health verification.
4. Application releases: one CI build, immutable digest, reviewed promotion commits, Argo reconciliation.
5. Emergency changes: time-bounded break glass, audit record, immediate Git reconciliation or documented rollback.

## Bootstrap invariant

The intended steady state has exactly two imperative in-cluster actions: install a pinned Argo CD release and apply the root Application. Initial Rancher/Argo multi-cluster registration may remain an explicitly documented bootstrap exception where credentials cannot safely be Git-managed.

## Drift and recovery authority

| Failure | Recovery authority |
|---|---|
| Verda instance/volume drift | Terraform configuration and protected state |
| Host drift | Ansible convergence or host rebuild |
| Kubernetes desired-state drift | Argo CD reconciliation from Git |
| Bad application release | Git revert to previous immutable digest |
| Cluster-state loss | RKE2 etcd snapshot plus Git reconciliation |
| Namespace/PVC loss | Velero/Longhorn restore plus checksum validation |
| Secret-controller loss | Encrypted off-repository Sealed Secrets recovery key |

Manual console work is allowed only for credentials/billing, a provider capability gap, or break-glass recovery. Every exception must record the operator, time, reason, affected resource, resulting drift, and reconciliation action.

## Phase 4 management-cluster bootstrap boundary

- RKE2 preparation and start are separate Ansible actions. Preparation cannot start until the
  read-only Terraform/state/cost boundary, complete Phase 3 verification, route/CIDR gate, and
  rollback-protected firewall update pass.
- The first server becomes healthy before either join; joins are serial and use WireGuard `9345`.
  Common immutable configuration is parity-hashed across all three nodes.
- The RKE2 token and protected direct/primary kubeconfigs live only in the external ACL-restricted
  controller directory. The token recovery copy is DPAPI sealed for the current operator.
- S3 values are process-only and are applied to the cluster through standard input with secret
  logging disabled. Acceptance requires both `file://` and `s3://` snapshot listings.
- Failure drills stop only one RKE2 server at a time and restore full health before the next drill.
  The default primary endpoint SPOF and protected direct-node recovery path are tested separately.
- On 2026-08-19, the authorized exact-source allowlist recovery, object-storage entitlement, and
  complete preflight closed the earlier blockers. The serial bootstrap produced three Ready
  server/etcd nodes, common-config parity, healthy Cilium/networking, and local plus off-cluster
  snapshots without changing a Verda infrastructure resource.
- Terraform remains authoritative for the unchanged three-instance/six-volume boundary. Ansible now
  owns the live RKE2 configuration and snapshot schedule. The manually created object-storage bucket
  and credential are an explicit provider-gap exception with separate teardown obligations.
- Failure drills, stability, active-cluster idempotency, and support-bundle proof passed during the
  definitive bootstrap. Independent current-tree verification, final local quality, PR validation,
  and protected-main hosted CI passed. Phase 4 is closed.

## Phase 5 GitOps ownership boundary

- The pinned bootstrap installed only Argo CD and applied one root Application. Its replay reached
  Helm revision 5 without ownership conflict and refreshed protected external account sessions.
- The root owns an exact eight-child Application set. All nine Applications are Healthy and Synced;
  no manual Helm release owns cert-manager, Longhorn, certificates, or ingress desired state.
- Git admitted the production certificate and public Argo ingress only after staging issuance
  passed. Argo's external surface is trusted TLS plus authenticated access; plain HTTP is limited to
  ACME solver behavior and otherwise returns 404.
- Longhorn owns only the dedicated data disks. The critical three-replica checksum fixture survived
  rescheduling, and the test cleanup left no temporary workload or volume artifact.
- Protected direct kubeconfig access remains independent of Argo ingress and future Rancher. All
  kubeconfigs, account sessions, endpoints, and raw live reports remain outside Git.
- Phase 5 is not closed until hosted closeout CI passes and merges. Phase 6 and
  every broader Stage A component remain inactive until that gate is recorded.
