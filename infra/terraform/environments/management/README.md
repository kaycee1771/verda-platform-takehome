# Stage A management infrastructure root

This is the only live Terraform root authorized in Phase 2. It creates one SSH
key record, three `CPU.4V.16G` instances in `FIN-03`, three instance-owned 80 GiB
OS disks, and three independently managed 100 GiB NVMe data volumes. The exact
Ubuntu 24.04 Minimal configuration ID is pinned in the input contract.

Provider 1.1.2 canonicalizes that UUID to `ubuntu-24.04` on read, so the
provider field receives the slug to remain idempotent. The immutable UUID is
still pinned, published in the summary output, and revalidated against that slug
through the live API before every plan/apply. See ADR 0012.

Authentication is read by provider 1.1.2 from `VERDA_CLIENT_ID` and
`VERDA_CLIENT_SECRET`; neither is a Terraform variable. The dedicated public-key
path is passed through `TF_VAR_ssh_public_key_path`. The canonical Make targets
initialize the partial local backend to a protected path outside the repository.
On this Windows workstation, the canonical state is sealed with current-user
DPAPI at rest, opened only for a Terraform process, and atomically resealed in a
`finally` path. A separate timestamped DPAPI backup is also round-trip verified.

No startup script is created. SSH-key injection is the only bootstrap behavior;
Ansible owns host configuration beginning in Phase 3.
The minimal image injects the provisioned key for `root`; Phase 3 uses that
bootstrap identity only long enough to create and verify the non-root
administrative account, then disables direct root SSH.
