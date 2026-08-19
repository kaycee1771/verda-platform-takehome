# Phase 5 Preflight Cluster Health

Status: PARTIAL — safe read-only cluster checks pass; remaining mutation
prerequisites are explicit.

On 2026-08-19 the protected direct Kubernetes path reported exactly three Ready,
schedulable nodes and 33 active scheduled pods. The preceding Phase 4 protected-main
verification remains green and proves etcd, Cilium/Hubble, CoreDNS, Traefik, audit,
encryption, snapshot, resilience, and stability gates from the accepted baseline.

Strict-host-key SSH read-only checks found on all three nodes:

- the dedicated Longhorn filesystem mounted;
- `iscsid` active;
- an NFSv4 client present;
- mount propagation available.

No endpoint, node identity, route, Secret, kubeconfig, or raw status payload is
recorded here.

Still required before the first Phase 5 write:

- exact integrated commit and offline quality PASS;
- complete rendered manifest inventory and expected diff;
- security/reliability approval;
- cloud-authenticated Terraform zero-drift plan and current cost check;
- fresh local and off-cluster etcd snapshot;
- rollback inventory;
- acquisition of the single-writer live-mutation lease.
