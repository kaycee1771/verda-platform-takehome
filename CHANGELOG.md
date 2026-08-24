# Changelog

This file records evaluator-relevant releases. The detailed implementation history is retained in
[docs/history/implementation-changelog.md](docs/history/implementation-changelog.md).

## 2026-08-24

- Completed the three-node RKE2 platform and GitOps-managed Rancher, Argo CD, Harbor, monitoring,
  logging and isolated application environments.
- Verified immutable application delivery, TLS, storage, security controls, alerting, logging,
  hosted repository validation and evaluator read-only access paths.
- Replaced the stale Rancher evaluator credential through the supported server API and verified a
  dedicated read-only login without weakening RBAC or substituting administrator credentials.
