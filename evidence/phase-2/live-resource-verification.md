# Live resource verification

Verified 2026-08-17 through authenticated CLI, Terraform refresh, and direct SSH:

| Check | Result |
|---|---|
| Three on-demand `CPU.4V.16G` instances running in `FIN-03` | PASS |
| Three 80 GiB OS volumes plus three 100 GiB data volumes attached | PASS |
| Exact deterministic instance/data-volume names | PASS |
| Intended dedicated Ed25519 key attached to every instance | PASS |
| Unique public address per instance | PASS — three distinct values, values withheld |
| Intended-key SSH plus exact remote hostname on server-01 | PASS |
| Intended-key SSH plus exact remote hostname on server-02 | PASS |
| Intended-key SSH plus exact remote hostname on server-03 | PASS |
| Terraform attachment instance matches each node ID | PASS |
| Deterministic ignored Ansible inventory contains exactly three hosts | PASS |

The initial server-02 received the same address as server-01. After explicit authorization, the
saved recovery plan replaced only server-02 and its instance-owned OS disk. The protected
`verda-mgmt-data-02` creation timestamp remained `2026-08-17T07:05:08.577Z`; the replacement server
and OS disk were created at `2026-08-17T07:54:54.912Z`. This independently demonstrates that the
persistent data-volume object was preserved across compute replacement.

The repaired live API inventory reports three running instances and six attached volumes. The
canonical verifier then proved three unique state outputs and authenticated to each endpoint with
the dedicated key as `root`, asserting the exact expected hostname remotely. No firewall,
WireGuard, package, storage formatting, RKE2, or other host mutation was performed.
