# Terraform state boundary

- Backend: Terraform local backend outside the repository.
- Locking claim: local process locking only; no remote/multi-operator lock is claimed.
- At-rest control: current-user Windows DPAPI.
- Runtime behavior: open only for one canonical Make command, atomically reseal in `finally`, verify
  decrypt/hash equality, then remove plaintext state.
- Independent copy: timestamped DPAPI-encrypted backup in a separate user directory with checksum;
  round-trip verification passed before and after recovery and during the final state audit.
- Git status: no state, plan, private key, credential, or backup path is tracked.
- Remote state: S3 migration is deferred until object-storage entitlement, compatibility, encryption,
  and locking behavior are proven.

The sanitized state audit contains exactly seven resource addresses: three instances, three
persistent data volumes, and one SSH key. It includes no resource IDs or state values.
