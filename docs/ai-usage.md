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

## 2026-08-16 - Authenticated Phase 0 gate closure

- **Human-provided state:** The user signed in to the Verda console, applied the assignment credit, chose a seven-day Stage A review window, and selected no custom domain.
- **Assistant activity:** Codex performed read-only console inspection of billing, deployment catalog, OS configuration, block-volume pricing/locations, credential categories, and exposed networking controls. It correlated those observations with provider 1.1.2, CLI 1.8.1, current official Verda pricing/API/object-storage/billing documentation, and the blueprint gates.
- **Material decisions:** Select lean Stage A sizing, FIN-03, Ubuntu 24.04 Minimal, on-demand CPU nodes, `sslip.io`, and ADR-0005 Path B. Treat absent Cloud API credentials and object-storage entitlement as later gates rather than fabricating capability.
- **Verification:** No Deploy/Create/Confirm action was invoked; current usage remained $0.00/hour; cost math was independently encoded in `docs/cost.md` and repository validation.
- **Sensitive-data handling:** No credential, token, coupon, access key, private key, or project/user identifier is recorded in committed artifacts.

## 2026-08-16 - Phase 1 repository and quality system

- **Requested contribution:** Implement only the blueprint's Phase 1 repository and quality system,
  including clean bootstrap, CI parity, validation, rejection fixtures, documentation, and evidence.
- **Assistant activity:** Codex created the canonical ownership tree, fail-closed future-phase guards,
  pinned quality image, local cache bootstrap, pre-commit suite, GitHub Actions workflow, schema and
  policy fixtures, negative tests, templates, and repository contracts.
- **Version validation:** Tool, Kubernetes, RKE2, chart, action, base-image, and CRD pins were checked
  against official release metadata and version-specific primary documentation. No unverified future
  CLI was represented as installed.
- **Correction after testing:** The initial non-root image lacked a passwd entry for UID 65532, which
  caused the generated-private-key negative test to fail before Gitleaks ran. A non-login user entry
  was added while retaining a numeric final `USER`, and the full rejection suite was rerun.
- **Rejected approach:** Aqua's standard registry returned 404 for a raw commit ref. The supported
  release ref was retained, and bootstrap now proves it resolves to the locked commit before Aqua
  installs checksum-verified packages.
- **Correction after testing:** Pre-commit initially invoked PyMarkdown without the committed config
  used by `make validate`. The hook now passes the same config explicitly; all hooks were rerun over
  the full staged file set.
- **Correction after clean-clone testing:** A broad `generated/` ignore pattern hid the required
  generated-inventory sentinel from Git even though the local structure check passed. The rule was
  narrowed to the repository root, the sentinel became an explicit contract file, and the clean-
  clone sequence was restarted from a new commit.
- **Reproducibility correction:** Identical BuildKit layers produced different local image-index
  digests because default provenance includes timestamps. For this local validator only, automatic
  provenance attachment was disabled and source-lock/checksum provenance was recorded explicitly;
  signed SBOM and provenance requirements for Phase 6 application artifacts remain unchanged.
- **Schema discipline:** Codex replaced future-only schema declarations with checksummed upstream
  schemas and positive fixtures for Argo CD, Kyverno, Kueue, Longhorn, Velero, Prometheus Operator,
  and Sealed Secrets. An unknown custom API remains a mandatory rejection case.
- **Human authority retained:** No repository remote, branch protection, CODEOWNERS identity, cloud
  credential, or Verda resource was inferred or created. Hosted CI publication remains a human-
  authorized external action.
- **Sensitive-data handling:** Validation received no cloud credentials. The private key used to test
  Gitleaks was generated only under ignored `.local/`, redacted in reports, and removed by a trap.
