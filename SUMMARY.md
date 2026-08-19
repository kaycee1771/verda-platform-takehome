# Verda Platform Take-Home Summary

This repository is being delivered as a phased platform product. Phase 0 fixed the architecture,
provider capabilities, Stage A cost envelope, and promotion gates. Phase 1 established a
reproducible credential-free quality system. Phase 2 then provisioned and proved the exact Stage A
infrastructure boundary: three Verda management instances, three protected data volumes, unique
public endpoints, dedicated-key SSH, encrypted external state, bounded rollback, cost compliance,
and final zero drift. Phase 3 then established and live-proved the complete pre-Kubernetes host
security, network, and storage boundary. Phase 4 has now completed its definitive guarded bootstrap:
the three-node RKE2 management cluster, failure drills, recovery points, hardening checks, support
bundle, active-cluster idempotency, and stability window all passed. An independent verification
rerun of the corrected current tree, final current-tree local quality, PR validation, and
protected-main hosted CI also passed. Phase 4 is closed. Phase 5 has now passed its protected live
bootstrap, GitOps ownership, Longhorn resilience, certificate, authenticated ingress, direct-access,
and external-boundary gates. Its final current-tree local CI passes; closeout remains partial only
until hosted CI is recorded and merged.

Current verified capabilities:

- Exact, source-attributed version and compatibility lock.
- Canonical Makefile interface with explicit future-phase guards.
- Containerized local/CI validators that run offline after bootstrap.
- Terraform, Ansible, YAML, shell, Helm, Kubernetes/CRD, Kyverno, Prometheus,
  Dockerfile, workflow, Markdown, and secret quality gates.
- Generated negative fixtures proving invalid inputs are rejected.
- Reusable Terraform modules and a plan-asserted Stage A management root.
- Three live `CPU.4V.16G` nodes in `FIN-03`, each with an 80 GiB OS disk and protected 100 GiB data
  volume.
- Sanitized evidence for resource identity, attachment, reachability, recovery, state, cost, drift,
  and the final hosted quality run.
- Three hardened Ubuntu 24.04 hosts with pinned key-only named administration, controlled security
  updates, audit/time/storage prerequisites, and public default-drop nftables policy.
- Node-local WireGuard identities, 1420-byte host overlay, reserved 1370-byte Cilium MTU, all six
  no-fragment peer paths, sustained ring traffic, and exact peer endpoint allowlists.
- Ext4 data volumes mounted by UUID at `/var/lib/longhorn` only after full empty-media proof, with
  clean idempotent reruns and persistence across three serial reboots.
- Three Ready and schedulable RKE2 server/etcd nodes with encrypted secrets, audit logging, healthy
  embedded etcd, and checksum-pinned bundled Cilium and Traefik.
- Complete unfiltered Hubble-disabled Cilium functional coverage plus a Hubble-enabled strict flow
  canary, bounded event buffering, exact per-agent/source zero lost-event delta across that canary,
  DNS/service/policy/MTU proof, and internal three-node ingress.
- Local and off-cluster compressed etcd snapshots, focused all-node CIS checks, approved-source
  public-port proof, one-node and primary-endpoint drills, and sanitized diagnostic collection.
- A 270-second post-drill stability window and active-cluster convergence replay with no changes,
  failures, or unreachable hosts.
- A pinned, idempotent Argo CD bootstrap whose one root Application owns an exact eight-child
  desired-state set; all nine Applications are Healthy and Synced.
- cert-manager with six ready controller replicas, staging-first and production certificate paths,
  and consistent trusted TLS served through all three protected ingress addresses.
- Three-node Longhorn on dedicated data disks, with three healthy critical replicas and a verified
  4 MiB checksum fixture preserved through cross-node rescheduling and cleanup.
- Authenticated Argo CD access with anonymous denial, a verified administrator, and a reviewer that
  can read but cannot sync or invoke actions; public HTTP remains ACME-only while HTTPS is healthy.
- Positive post-install one-node-loss scheduling headroom and an exact public boundary of four
  allowed and 28 denied TCP port classes on each of three nodes.

Phases 0–4 are complete. Phase 5 live gates and final local CI pass, but Phase 5 remains PARTIAL
until hosted closeout CI passes and merges. Stage B, the application, and Phase 6+
functionality remain fail closed behind their owning gates.
