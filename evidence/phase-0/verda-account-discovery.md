# Evidence: Read-Only Verda Account Discovery

- Collected: 2026-08-16
- Verda CLI: 1.8.1 (`windows/amd64`, SDK 1.4.2)
- Mode: agent/non-interactive allowlisted read-only queries
- Explicit acknowledgement: supplied with `-ConfirmReadOnly`
- Credential values captured: no
- Cloud mutation attempted: no
- Secret values printed: no
- Browser fallback: in-app browser and connected Chrome both redirected to Verda sign-in; no credentials entered

## Result

**BLOCKED.** Credential-presence booleans were false. Local doctor and non-secret status commands completed; account-backed inventory and cost calls returned authentication errors.

| Query group | Result |
|---|---|
| CLI doctor | PASS |
| Credential status | No active API credentials |
| Locations | AUTH_ERROR |
| CPU types/prices | AUTH_ERROR |
| Images | AUTH_ERROR |
| Full per-location availability matrix | AUTH_ERROR |
| Volumes | AUTH_ERROR |
| Account status/running cost/balance | AUTH_ERROR |
| Object-storage status | Command PASS; S3 access not tested |
| Registry status | Command PASS; registry not selected as Harbor substitute |

This evidence proves fail-closed behavior, not account capability. No image, shape, price, balance, or network conclusion is made.
