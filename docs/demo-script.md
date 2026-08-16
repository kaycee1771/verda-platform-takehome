# Demo Script

## Phase 1 repository demonstration

1. Run `make help` and show the canonical commands plus explicit future-phase guards.
2. Run `make bootstrap-tools` from a clean clone and review the pinned-version report.
3. Run `make validate` with the Docker network disabled.
4. Run `make validate-negative` and show all four invalid artifacts being rejected.
5. Run `make secret-scan` and inspect only the clean, redacted reports.
6. Open `.github/workflows/validate.yml` and compare it with `make ci`.

The live platform demonstration is intentionally deferred until its infrastructure and verification
phases are complete.
