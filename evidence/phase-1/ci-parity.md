# Phase 1 CI-Parity Evidence

## Local result

`make ci`: **PASS**

The target executed, in order, the complete positive validator, all five negative gates, every
pre-commit hook over the staged/tracked repository, and a second standalone working-tree/history
Gitleaks scan. The container had networking disabled and received no cloud credentials.

The ignored final `ci.log` is 9,956 bytes with SHA-256
`a94b5d9128dc74b88ffa2f75954e2fb89e4276dcb870e49f87fa218f0c4aa070`.
The workflow source has SHA-256
`1ea87aca8e3dc9e9ccd4a0cb287760f84094cb1c2bdbd4ef40e306e7d686d3bd` and passes actionlint.

## Hosted boundary

No GitHub remote is configured, so a hosted Actions run, branch protection, and a resolvable
CODEOWNERS identity cannot be truthfully evidenced. The workflow is least-privilege, pins every
third-party action by full SHA, restores only non-sensitive caches, runs the same `make ci` target,
and uploads only `.local/reports/` for seven days.

Hosted CI remains the sole Phase 1 external closure item; it does not authorize Phase 2.

The isolated-clone CI rerun is 10,122 bytes with SHA-256
`32482bf0955aeea9f7e9b4f6a496535189d9940368953927d017d5ca2a2788cc`.
