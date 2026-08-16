# Repository Security Controls

The authoritative disclosure and secret-response process is [SECURITY.md](../SECURITY.md). Phase 1
adds reproducible secret scanning, private-key detection, immutable CI action pins, least-privilege
workflow permissions, and a credential-free validation boundary.

No exception may disable secret or Kubernetes schema validation globally. A narrow exception must
identify its owner, scope, reason, expiry, and compensating control.
