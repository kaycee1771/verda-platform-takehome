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

## 2026-08-16 - Phase 1 hosted closure and repository governance

- **Human authorization:** The user supplied `kaycee1771/verda-platform-takehome`, verified the
  `Kaycee1771` owner identity, authorized publication and repository governance, then explicitly
  authorized public visibility after GitHub Free rejected protection on a private repository.
- **Hosted correction:** The first GitHub Actions run exposed a Linux bind-mount ownership defect:
  bootstrap assigned all `.local/` files to validator UID 65532 before host PowerShell wrote its
  report. Bootstrap now makes the Linux runner UID the owner and validator GID 65532 the group, with
  `u+rwX,g+rwX,o-rwx`; the full local suite and corrected hosted run passed.
- **Action maintenance:** GitHub reported the old artifact action's Node 20 runtime as deprecated.
  Codex verified official v7.0.1 release metadata and resolved the upstream tag to full commit
  `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` before changing the workflow pin.
- **Governance correction:** GitHub rejected empty organization-only user/team restriction objects
  in the initial personal-repository protection payload. No partial rule was applied. Those
  unsupported fields were removed; required CI, PRs, administrator enforcement, linear history,
  conversation resolution, and force-push/deletion denial were then verified through the API.
- **Security:** GitHub secret scanning and push protection are enabled. CLI authentication remained
  in the OS keyring; no token, credential, private key, or cloud secret was added to the repository
  or committed evidence.
- **Boundary:** No Verda Cloud resource, credential, DNS record, Kubernetes component, or Phase 2
  implementation was created or modified.

## 2026-08-16 - Phase 1 review reconciliation before Phase 2

- **Review findings:** The committed workflow already used `actions/upload-artifact` v7.0.1 at its
  immutable SHA, while the separate version lock still described v4.6.2; hosted evidence also
  referenced the preceding successful run instead of the final protected `main` run.
- **Assistant activity:** Codex aligned the lock, added a validator that rejects floating, unknown,
  unused, and lock-mismatched remote Action references, added a deliberate mismatch rejection test,
  and refreshed Phase 1 evidence to commit `751cd2e1d77d88d34a8afaf40e40683cc01e8a8e` and run
  `31961790627`.
- **Verification:** The complete Docker-isolated `make ci` contract passed locally without cloud
  credentials before any Phase 2 account inspection or mutation.
- **Boundary:** This reconciliation changed repository quality controls only. No Verda Cloud
  credential or resource was created or modified.

## 2026-08-17 - Phase 2 provisioning and fail-closed runtime corrections

- **Human authorization:** The user authorized Phase 2, created no credential value in chat, signed
  into the console, and explicitly confirmed creation of a time-bound Cloud API credential.
- **Assistant activity:** Codex created reusable provider-1.1.2 modules, a three-node management
  root, native mock tests, saved-plan assertions, cost controls, DPAPI state handling, deterministic
  inventory generation, and guarded lifecycle operations.
- **Credential correction:** The console's two unlabeled copy controls were initially interpreted in
  the wrong order. The first authentication probe returned 401; Codex swapped only the two in-memory
  variables, proved authentication, and never displayed or persisted either value.
- **State correction:** Windows EFS returned `request is not supported`, so the design was changed to
  current-user DPAPI sealing. An initial PowerShell generic byte-comparison call failed after apply;
  SHA-256 byte-array comparison replaced it, state was immediately sealed, and an independently
  located encrypted backup passed a decrypt/hash round trip.
- **Provider correction:** Provider 1.1.2 accepted the pinned image UUID but returned
  `ubuntu-24.04`, causing an inconsistent-result error after all resources were created. Codex
  rejected `ignore_changes` and a local provider fork. ADR 0012 retains the immutable UUID as the
  live invariant while using the official stable API image type as the provider transport value.
- **Fail-closed finding:** Two VM records received the same public address. Direct SSH proved that
  address reaches server-01, leaving server-02 without an independent endpoint. Codex rejected the
  resulting three-instance replacement plan, stopped further cloud mutation, and left corrective
  compute replacement behind explicit confirmation.
- **Verification:** The complete credential-free `make ci` suite passed before apply; initial plan
  assertions admitted exactly seven resources and no credential values; live inventory shows three
  running instances, six attached volumes, and a reconciled $0.23165 hourly rate.
- **Recovery authorization:** The user later authorized only server-02 compute and its instance-owned
  OS disk replacement while preserving its persistent data volume. Codex implemented two guarded
  Make targets and a plan mode that rejected every address/action except that exact replacement.
- **Recovery result:** The saved plan contained one `delete/create`; encrypted backups passed before
  and after apply; the original server-02 data-volume creation timestamp remained unchanged; and the
  final plan contained zero resource actions.
- **Verification corrections:** The first post-repair uniqueness check correctly stopped on stale
  Terraform outputs; a zero-resource refreshed plan persisted the new output. A PowerShell quoting
  defect then caused the remote hostname expression to run locally; Codex interrupted the read-only
  retry, corrected and regression-tested the literal command, and reran all three SSH assertions.
  Final CI then rejected the generated inventory because it lacked YAML's document marker; the
  generator was corrected instead of weakening Ansible lint.
- **Final boundary:** Three unique endpoints, exact attachments, hostname-bound SSH, inventory,
  lifecycle, cost, state, backup, and no-drift gates pass. No host configuration, WireGuard,
  firewall, RKE2, Kubernetes, Rancher, Argo CD, Harbor, DNS, or Stage B action occurred.
