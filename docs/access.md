# Assessor Access Instructions

**Status:** Phase 0 template. Do not add live passwords, private keys, administrator kubeconfigs, or recovery material to this file.

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
| SSH | OPEN | 22 | Named administration user or no assessor access | Public key allowlist | OPEN |

## Verification flow

This section will contain copy-paste-safe commands for DNS, TLS, login, application version, Argo health, Harbor artifact, Prometheus query, Loki query, and backup status.

## Revocation

The final runbook must identify who revokes assessor users, SSH keys, robot credentials, DNS records, and running infrastructure after the review window.
