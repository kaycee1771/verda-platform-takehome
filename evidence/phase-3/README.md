# Phase 3 Evidence Index

Phase 3 converted the three live Stage A instances into hardened, reboot-stable RKE2-ready hosts
without installing RKE2 or changing any Verda Cloud resource. The acceptance run completed on
2026-08-17 and all Phase 3 exit gates passed.

| Evidence | Proof |
|---|---|
| [preflight-and-boundary.md](preflight-and-boundary.md) | Exact live resource/state/cost boundary, zero drift, no cloud mutation |
| [host-hardening-report.md](host-hardening-report.md) | Operating-system, access, service, kernel, update, and recovery controls |
| [ansible-idempotency.md](ansible-idempotency.md) | Sanitized first, second, final, and post-reboot convergence results |
| [external-port-scan.md](external-port-scan.md) | Allowed SSH and denied public application/control-plane ports |
| [wireguard-reachability.md](wireguard-reachability.md) | Six directed MTU paths, authenticated handshakes, and sustained ring traffic |
| [mount-uuid-report.md](mount-uuid-report.md) | Stable identity, guarded format, UUID persistence, ownership, and free-space checks |
| [reboot-and-exit-gates.md](reboot-and-exit-gates.md) | Three serial reboot proofs and every blueprint exit-gate result |
| [repository-validation.md](repository-validation.md) | Bootstrap, positive/negative gates, hooks, secret scans, and CI parity |

The ignored local reports under `.local/reports/phase3/` are the structured source for these
summaries. Raw Ansible logs, generated inventory, endpoint addresses, administrative CIDRs, resource
IDs, filesystem UUIDs, SSH material, WireGuard private keys, Terraform state, and credentials are
deliberately excluded from committed evidence.
