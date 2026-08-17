# Repository and Quality Validation

## Result

**PASS.** The finished Phase 3 tree completed the canonical tool bootstrap and credential-free CI
parity contract.

| Command | Result |
|---|---|
| `make bootstrap-tools` | PASS; exact image/tool lock and offline caches verified |
| `make validate` | PASS; all applicable positive validators |
| `make validate-negative` | PASS; all six invalid fixtures rejected |
| `make pre-commit` | PASS; every all-files hook |
| `make secret-scan` | PASS; working tree and complete Git history, no leaks |
| `make ci` | PASS; the complete local GitHub Actions parity chain |

The first bootstrap cache refresh encountered repeated upstream HTTP 429 responses. The quality
system was strengthened rather than bypassed: downloads now use bounded retry/backoff, source blobs
receive content-addressed cache paths, and every materialized CRD output has its own committed
SHA-256 integrity lock. Unit tests prove valid-cache acceptance, invalid-cache rejection, retry
behavior, output-lock presence, and post-download checksum rejection. A repeat bootstrap then passed
using only verified cache hits for schemas.

The first cold-cache hosted run on the published Phase 3 pull request later proved that bounded
anonymous retries alone were insufficient on a shared runner: GitHub continued returning HTTP 429
after the final attempt. The approved portability correction supplies the job-scoped, read-only
`GITHUB_TOKEN` only to bootstrap, maps locked GitHub raw URLs to the official Contents API, and
forwards the credential to no other host or validation phase. Eight focused tests cover the host
allowlist, authenticated raw-media request, unauthenticated local behavior, checksum rejection,
retry behavior, and log non-disclosure. The rebuilt bootstrap and complete 37-test offline `make ci`
suite pass locally; the protected pull-request check remains the independent hosted enforcement.

No cloud credential is mounted into the quality container and its network is disabled for all
validation, negative, hook, secret-scan, and CI runs.
