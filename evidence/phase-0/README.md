# Phase 0 Evidence Index

Evidence is sanitized, dated, tied to the current repository state, and intentionally contains no project/account identifiers, credentials, tokens, instance IDs, or public IPs.

| Evidence | Purpose | Result |
|---|---|---|
| `provider-schema-summary.md` | Exact provider 1.1.2 resource/data-source contract | PASS |
| `verda-account-discovery.md` | Read-only current-account catalog, balance, credential, and storage probe | PASS |
| `network-capability-surface.md` | Provider/CLI/console network boundary and Path B basis | PASS |
| `stage-a-cost-envelope.md` | Reproducible seven-day cost calculation against live balance | PASS |
| `validation-summary.md` | Repository/tool/test results | Updated by final Phase 0 verification |
| `../manifests/phase-0-acceptance-matrix.md` | Immutable Phase 0 requirement snapshot | PASS |

Raw schema and CLI account outputs use the ignored `*.local.json` convention and are never committed. Catalog image IDs may be recorded; account/project/user IDs and credentials may not.
