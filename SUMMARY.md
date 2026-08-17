# Verda Platform Take-Home Summary

This repository is being delivered as a phased platform product. Phase 0 fixed the architecture,
provider capabilities, Stage A cost envelope, and promotion gates. Phase 1 established a
reproducible credential-free quality system. Phase 2 then provisioned and proved the exact Stage A
infrastructure boundary: three Verda management instances, three protected data volumes, unique
public endpoints, dedicated-key SSH, encrypted external state, bounded rollback, cost compliance,
and final zero drift. Phase 3 then established and live-proved the complete pre-Kubernetes host
security, network, and storage boundary.

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

Phase 3 host hardening and secure node networking are complete. RKE2, Kubernetes,
GitOps, platform services, Stage A verification, Stage B, and the application remain unimplemented
and fail closed behind their blueprint phases.
