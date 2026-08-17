# Reboot and Phase 3 Exit Gates

## Serial reboot proof

**PASS.** Each node was rebooted independently while the other two remained available. For every
node the runner:

1. captured the current kernel boot identity;
2. scheduled the reboot through a transient systemd unit;
3. observed SSH leave and return;
4. rejected a return under the old boot identity;
5. waited for cloud-init to settle;
6. proved strict `platform-admin` access;
7. reran host, WireGuard, firewall, time, storage, and RKE2-absence diagnostics.

All three returned with new boot identities. The following full prepare/network convergence was
zero-change on every host.

## Exit-gate result

| Blueprint condition | Result | Proof |
|---|---|---|
| All three hosts pass the baseline | PASS | Final diagnostics: 3/3, zero failed/unreachable |
| Internal node addressing is stable | PASS | Fixed overlay mapping, 6/6 directed paths, recent handshakes, reboot survival |
| Firewall rules are validated | PASS | Fresh admin sessions, external allow/deny scan, default-drop table, peer-only WireGuard |
| A node reboot preserves configuration | PASS | Stronger result: all three serially rebooted and passed; post-reboot convergence zero |
| Candidate retains safe administrative access | PASS | Key-only named admin succeeds; root/password fail; host keys pinned; recovery timers exercised |

RKE2, Kubernetes, Rancher, Argo CD, Harbor, DNS, Stage B, and all Phase 4+ targets remain
unimplemented and blocked. Phase 4 requires explicit authorization.
