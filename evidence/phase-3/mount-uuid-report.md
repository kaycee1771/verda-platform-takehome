# Persistent Data-Mount Evidence

## Result

**PASS on all three hosts before and after reboot.** Raw filesystem UUIDs and provider volume IDs
are not recorded.

| Contract | Result |
|---|---|
| Provider-stable attachment identity | Exact expected attachment on each host |
| Candidate block device | Exact 100 GiB whole disk; no partition tree |
| First-format guard | Every byte proved zero before ext4 creation |
| Unexpected signatures | Fail closed; none observed |
| Persistent source | `UUID=` entry in `/etc/fstab` |
| Mount | `/var/lib/longhorn`, ext4 |
| Ownership and mode | `root:root`, `0750` |
| Minimum observed free space | 105,072,459,776 bytes |
| Reboot persistence | Mounted with the same hashed UUID identity on all three nodes |
| Repeat execution | Zero scan and format skipped; no changes |

The ignored structured report stores a SHA-256 digest of each UUID solely to correlate identity
without disclosing the raw value. It reports `raw_uuid_recorded=false`.
