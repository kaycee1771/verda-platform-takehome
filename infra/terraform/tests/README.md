# Phase 2 Terraform verification

The management root carries native mock-provider tests in its `tests/`
directory. `scripts/infra/assert-plan.py` additionally verifies the saved live
plan: exact create counts, allowlisted resource types, immutable selections,
non-sensitive outputs, preservation policy, and credential absence.

Both test paths run without applying resources. The live plan assertion consumes
Terraform JSON in memory and writes only a sanitized summary.
