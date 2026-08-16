# AI Usage Log

This file exists to make AI assistance auditable rather than performative. Entries record the contribution, the human-controlled decision, and the verification method.

## 2026-08-16 - Phase 0 architecture and governance

- **Assistant:** OpenAI Codex. This is not Claude, and the submission must not claim otherwise.
- **Requested contribution:** Extract the assignment, design a senior/staff-level execution strategy, and implement Phase 0 governance artifacts.
- **Accepted assistance:** Requirement decomposition, architecture options, ADR framing, risk and assumption registers, proof-oriented acceptance criteria, and safe discovery script design.
- **Human authority retained:** Credit redemption, credential creation, cloud access, topology approval, external account choices, and all resource mutations.
- **Verification:** Assignment text was extracted and visually checked; current technical claims were checked against primary vendor documentation; repository validation is automated by `scripts/phase0/validate.ps1`.
- **Rejected behavior:** No attempt was made to fabricate cloud evidence, claim use of Claude, install unapproved infrastructure, or treat installed components as proof of operability.

Future entries must identify generated code that was materially changed after testing and any AI suggestion rejected because it conflicted with observed platform behavior.

## 2026-08-16 - Authoritative blueprint reconciliation

- **Assistant:** OpenAI Codex; not Claude.
- **Planning input:** `VERDA_PLATFORM_TAKEHOME_MASTER_BLUEPRINT.md`, SHA-256 `D7C2BE53EA0777DDC14041DE9D79B074D5E314AFC655C80FAF350CFD47B4E37A`.
- **User instruction:** Treat the blueprint as authoritative, execute Phase 0 only, inspect account/provider/docs rather than guessing, and stop at the Phase 0 gate.
- **Correction made:** The earlier Codex baseline treated a co-located three-node cluster as the final implementation. The blueprint requires that topology only as Stage A and selects a separate workload cluster as the conditional Stage B gold target. ADR-0002 and the architecture contract now record the change explicitly.
- **Provider validation:** Codex re-exported the lockfile-selected `verda-cloud/verda` 1.1.2 schema and compared it with current official Verda and Terraform Registry documentation. Documentation-only fields absent from the schema were rejected.
- **Account validation:** The read-only discovery attempt was retained as a blocker because API credentials were absent. Codex did not fabricate images, flavors, prices, credits, or network capabilities.
- **Human authority retained:** The user must obtain/store credentials, confirm credit redemption, approve any major architecture change, and later supply a genuine Claude interaction if the literal assignment requirement is to be demonstrated.

## Genuine Claude interaction placeholder

Not yet performed. A later bounded review must record the Claude prompt, output, human verification, corrections, and exact artifact influenced. No Codex work will be relabeled as Claude output.
