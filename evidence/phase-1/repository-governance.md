# Phase 1 Repository Governance Evidence

## Verified state

The user explicitly authorized public visibility for
[`kaycee1771/verda-platform-takehome`](https://github.com/kaycee1771/verda-platform-takehome) after
GitHub Free returned HTTP 403 for protection on the private repository. Live GitHub API reads then
verified:

- Visibility is `public`; default branch is `main`.
- CODEOWNERS names the verified `@Kaycee1771` identity globally and for infrastructure, platform,
  policy, production-environment, and workflow paths.
- `main` requires the successful `Credential-free quality gates` check from GitHub Actions app ID
  `15368`; strict mode requires the PR branch to be current.
- Pull requests are required, stale reviews are dismissed, and unresolved conversations block merge.
- Administrator enforcement and linear history are enabled.
- Force pushes and branch deletion are disabled.
- Squash is the only merge method, pull-request branches may be updated, and merged branches are
  deleted automatically.
- GitHub secret scanning and secret-scanning push protection are enabled.

## Single-owner review tradeoff

The protection rule requires the pull-request boundary but sets the approval count to zero and does
not require a CODEOWNERS approval. GitHub does not allow an author to approve their own change, so a
one-approval rule would make this single-owner take-home repository impossible to operate. The
required app-bound CI, current-branch check, conversation resolution, administrator enforcement,
and immutable merge history remain mandatory. A real team should raise approval count and enable
required CODEOWNERS review once an independent reviewer identity exists.

## API correction record

The first protection request returned HTTP 422 because empty organization-only user/team review
restriction objects are invalid for a personal repository. GitHub applied no partial state. Codex
removed only those unsupported fields and verified the complete supported policy through the live
branch-protection and repository APIs.

These GitHub controls govern source delivery only. They do not authorize Phase 2 or prove any Verda
Cloud, Kubernetes, GitOps, registry, DNS, application, or recovery capability.
