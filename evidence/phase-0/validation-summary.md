# Phase 0 Validation Summary

- Collected: 2026-08-16
- Active phase: 0
- Cloud resources created/changed: 0
- Repository-side result: PASS
- Phase 0 exit-gate result: BLOCKED

## Commands and outcomes

| Command/check | Outcome |
|---|---|
| `pwsh -NoProfile -File scripts/phase0/validate.ps1` | PASS — 184 checks passed, 0 failed |
| `terraform -chdir=infra/terraform/provider-discovery fmt -check` | PASS |
| `terraform -chdir=infra/terraform/provider-discovery validate` | PASS — configuration valid |
| `terraform ... plan -refresh=false -input=false -lock=false -detailed-exitcode` | PASS — no changes; discovery root declares zero resources |
| Exact provider schema export | PASS — provider 1.1.2, eight resources, zero data sources |
| Authenticated allowlisted account discovery | BLOCKED — expected non-zero; no credentials; API queries returned authentication errors |
| In-app and Chrome console fallback | BLOCKED — both redirected to Verda sign-in; no login attempted |
| `git diff --check` | PASS — no whitespace errors |
| Working-tree secret/sensitive-filename heuristics | PASS — no private-key or populated Verda-secret markers |

## Exit-gate result

| Condition | Result |
|---|---|
| Provider schema inspected | PASS |
| OS image and CPU instance type known | FAIL |
| Networking limitations verified against current account | FAIL |
| Acceptance matrix complete | PASS |
| Credible Stage A cost envelope within credit | FAIL |

Repository correctness does not override live evidence. Phase 1 remains NOT STARTED.
