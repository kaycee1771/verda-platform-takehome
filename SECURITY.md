# Security Policy

## Repository trust boundary

This repository stores desired state, automation, documentation, and sanitized evidence. It must never store live credentials or private recovery material.

Prohibited content includes:

- Verda client secrets or object-storage secret keys.
- SSH private keys.
- Kubernetes administrator kubeconfigs.
- Terraform or OpenTofu state and plan files.
- Sealed Secrets controller private keys.
- Rancher, Argo CD, Harbor, Grafana, or application passwords.
- Unredacted discovery output containing assessor-sensitive account data.

## Credential handling

- Local Verda authentication uses `VERDA_CLIENT_ID` and `VERDA_CLIENT_SECRET` environment variables or the Verda CLI credential store.
- CI credentials must come from the Git provider's encrypted secret store.
- Assessor credentials will be time-bounded, least-privilege accounts delivered out of band.
- Secret values must never be passed as command-line arguments when an environment variable or protected input is available.
- Debug logging is disabled for account discovery because HTTP debug output can expose sensitive headers.

## Reporting

If a secret is accidentally committed, stop work, revoke or rotate it first, then remove it from Git history. Treat deletion from the working tree alone as insufficient.
