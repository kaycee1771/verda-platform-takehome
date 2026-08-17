# Assessor Access Instructions

**Status:** Phase 3 host boundary verified; application and platform access remain future work. Do
not add live endpoints, source CIDRs, passwords, private keys, administrator kubeconfigs, or recovery
material to this file.

## Access principles

- Public repository documentation contains endpoints and role names, not secret values.
- Credentials are delivered out of band and expire after the assessment window.
- Every assessor account is least privilege and independently revocable.
- Administrative APIs use an allowlist or SSH tunnel where practical.
- A scripted access check confirms reachability without exposing credentials.

## Endpoint inventory

| Service | URL or tunnel | Public port | Assessor role | Credential delivery | Expiry |
|---|---|---:|---|---|---|
| Demo application - dev | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Demo application - staging | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Demo application - prod | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Rancher | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Argo CD | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Harbor | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Grafana | OPEN | 443 | Viewer | Out of band | OPEN |
| Kubernetes API | OPEN | 6443 or SSH tunnel | Read-only kubeconfig | Out of band | OPEN |
| SSH | Redacted direct endpoint | 22 | `platform-admin`; operator only in Phase 3 | Public key plus source `/32` allowlist | 2026-08-24 |

All service rows except SSH are design contracts, not live endpoints. TCP 80, 443, 6443, 9345,
2379–2381, 10250, 9090, and sampled NodePorts are currently filtered or closed externally. RKE2 and
all listed platform services remain absent.

## Verification flow

The Phase 3 host check is automated by `make verify-hosts CLUSTER=management` and uses external
runtime material. It proves pinned host identity, named key login, root/password denial, firewall,
WireGuard, storage, time, and RKE2 absence without printing endpoint or secret values. Later phases
will add copy-paste-safe DNS, TLS, scoped login, artifact, health, metrics, logs, and backup checks.

## Revocation

After the assessment, remove the administrator public key/account as part of teardown, revoke the
Cloud API credential, delete its operator-provided source image, remove external state/keys only
after required evidence retention, and destroy infrastructure through the guarded teardown phase.
Later phases must add reviewer, robot, DNS, and service-account revocation steps when those resources
exist.
