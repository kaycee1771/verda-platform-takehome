# Management RKE2 Installation

Status: PASS for installation, staged convergence, definitive bootstrap, and corrected current-tree
independent verification and final local quality on 2026-08-19. Phase 4 remains open for hosted CI.

The guarded Phase 4 orchestrator completed the following sequence without a Verda infrastructure
mutation:

1. Revalidated exactly three intended instances and six volumes, encrypted state recovery, zero
   Terraform drift, strict administrator access, all host controls, and the CIDR boundary.
2. Installed only checksum-pinned RKE2 artifacts and their bundled component archives.
3. Prepared all three servers without starting RKE2, then proved common critical configuration
   parity.
4. Started the primary and joined each additional server serially through the WireGuard
   registration path, waiting for node and etcd health after every start.
5. Reached three Ready, schedulable server/etcd nodes with healthy system components.

The installed contract is RKE2 `v1.35.7+rke2r1`, Kubernetes `v1.35.7`, embedded etcd
`v3.6.14-k3s1`, bundled Cilium `v1.19.6`, and bundled Traefik `v3.7.8`. Exact artifacts,
checksums, and authoritative sources remain in `version-selection.md` and `versions.lock.yaml`.

The cluster token, administrator kubeconfigs, certificates, recovery material, and S3 credentials
remain outside Git. Raw Ansible and service output remains ignored and is not evidence.
