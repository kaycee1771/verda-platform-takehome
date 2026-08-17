# Ansible Idempotency Evidence

## Result

**PASS.** The final full acceptance invocation completed two entire playbook sequences and a final
diagnostic pass. Every sanitized recap below reported `changed=0`, `unreachable=0`, and `failed=0`
on each of the three hosts.

| Acceptance run | Host recaps | Changed | Unreachable | Failed |
|---|---:|---:|---:|---:|
| First `prepare-hosts` | 3 | 0 | 0 | 0 |
| First `configure-network` | 3 | 0 | 0 | 0 |
| First `verify-hosts` | 3 | 0 | 0 | 0 |
| Second `prepare-hosts` | 3 | 0 | 0 | 0 |
| Second `configure-network` | 3 | 0 | 0 | 0 |
| Second `verify-hosts` | 3 | 0 | 0 | 0 |
| Final `verify-hosts` | 3 | 0 | 0 | 0 |

After all three serial reboots, the runner repeated `prepare-hosts` and `configure-network`; both
post-reboot recaps again reported zero changes on every host. Per-node post-reboot diagnostic plays
reported zero failures. This distinguishes declarative stability from a one-time successful setup.

The first mutation run necessarily changed the fresh hosts. During fail-closed live iteration it
also exposed and corrected image-owned locale/hosts behavior, absent systemd-unit handling,
nftables syntax, stable mount verification, and reboot-command completion. The table above is the
fresh final acceptance run after those corrections, not a claim that initial provisioning changed
nothing.
