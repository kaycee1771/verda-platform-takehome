# Phase 1 CI-Parity Evidence

## Local result

`make ci`: **PASS**

The target executed, in order, the complete positive validator, all six negative gates, every
pre-commit hook over the staged/tracked repository, and a second standalone working-tree/history
Gitleaks scan. The container had networking disabled and received no cloud credentials.

The post-portability fresh-clone `ci.log` is 9,950 bytes with SHA-256
`66424cf258a1690fd8acdfff6ffcbf6b1797fce9d352135ff544d3533bcdef3a`.
The workflow source at implementation commit `f4848cf` has SHA-256
`6e55290f2d8f080afabf27992ca9cf32902e98edb1126ac65c29f3b11b7e05ec` and passes actionlint.

## Hosted result

GitHub Actions run [`31961790627`](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/31961790627)
at `751cd2e1d77d88d34a8afaf40e40683cc01e8a8e` passed the same bootstrap and `make ci` contract on
`ubuntu-24.04` in 1 minute 33 seconds. It used read-only repository permissions, received no cloud
credentials, and uploaded only the non-sensitive `.local/reports/` set for seven days.

The first hosted run failed because Linux ownership assigned the ignored cache/report tree solely to
validator UID 65532 before host PowerShell wrote metadata. The corrected ownership contract uses the
runner UID as owner and validator GID 65532 as group with no world access. Local full CI, a fresh
remote-clone full CI, and the corrected hosted run all passed.

Hosted closure does not authorize Phase 2.
