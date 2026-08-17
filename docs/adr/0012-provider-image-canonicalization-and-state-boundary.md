# ADR 0012: Preserve Immutable Image Identity Across Provider Canonicalization

- Status: Accepted
- Date: 2026-08-17
- Decision owners: Platform engineering
- Scope: Phase 2 Verda infrastructure and Terraform state

## Context

Phase 0 selected Ubuntu 24.04 Minimal by immutable configuration ID
`77edfb23-bb0d-41cc-a191-dccae45d96fd`. Live discovery on 2026-08-17 again
proved that the Verda catalog maps this ID to `image_type=ubuntu-24.04` for
`CPU.4V.16G`.

Provider `verda-cloud/verda` 1.1.2 accepts the configuration ID in the create
request. During the first Phase 2 apply, however, each successful API response
returned `image=ubuntu-24.04`. Terraform reported `Provider produced
inconsistent result after apply` because the provider schema marks `image` as a
required replacement attribute and its flatten function writes the API value
back without preserving the planned representation. The three intended
instances were created, all seven planned resources were retained in state, and
no unplanned resource was created.

Official provider 1.1.2 examples pass image slugs such as
`ubuntu-24.04-cuda-12.8-open-docker`, confirming that `image_type` is the
provider's stable transport representation even though the console exposes an
immutable configuration ID.

The same apply surfaced that Windows EFS is unavailable on this workstation.
An ACL-only local state file would not meet the accepted encrypted-state
strategy.

## Decision

Maintain two explicit image values with different responsibilities:

- `os_image_id` remains the immutable reviewed identity and is pinned in the
  root contract, summary output, tests, plan summary, and evidence.
- `provider_image_value=ubuntu-24.04` is passed only to the provider resource.
- Before every plan or apply, the authenticated Verda CLI must prove that the
  live catalog contains exactly one image whose ID and `image_type` match this
  pair for `CPU.4V.16G`. A changed or ambiguous mapping is a hard stop.

Use current-user Windows DPAPI as the state-at-rest control:

- Terraform state is decrypted only for the duration of an operator command.
- A `finally` path atomically seals current and backup state, verifies a
  decrypt/hash round trip, and removes plaintext runtime files.
- A timestamped, independently located DPAPI backup and checksum are created
  after apply and material state changes.
- Local-backend process locking is claimed; multi-operator remote locking is
  not. S3 migration remains deferred until object-storage entitlement and
  locking behavior are proven.

## Consequences

- Terraform readback becomes idempotent without forking or inventing a provider.
- The immutable selection is still fail-closed, but enforcement spans the live
  preflight plus Terraform contract/output instead of the provider field alone.
- If Verda ever remaps `ubuntu-24.04`, planning stops before mutation.
- Direct raw Terraform commands bypass the DPAPI wrapper and are unsupported;
  the Make targets are the canonical operator interface.
- DPAPI recovery is bound to the current Windows user profile. The independent
  backup must be migrated to a portable encrypted mechanism before handoff or
  multi-operator production use.

## Alternatives rejected

- `ignore_changes=[image]`: hides real image drift and still does not guarantee
  a clean initial apply.
- Local provider fork: creates an unreviewed provider supply-chain and support
  burden for a bounded take-home.
- Recreate instances manually: violates the automation and repeatability
  contract.
- Store only a mutable display name: loses the live UUID invariant and weakens
  provenance.

## Verification

- Sanitized first-apply failure evidence records the UUID-to-slug mismatch.
- State audit proves exactly seven planned resource addresses and no resource
  IDs in the report.
- The post-decision plan must report zero changes.
- Full quality, secret-scan, lifecycle, SSH, attachment, and cost gates must
  still pass before Phase 2 can close.

## Phase 2 outcome

After explicit authorization, the recovery workflow cleared the provider-error taint from healthy
nodes 01 and 03 and applied an exact one-instance replacement plan for node 02. Its persistent data
volume was preserved. The final refreshed plan reported zero resource changes; encrypted state,
backup, lifecycle, three-host SSH, attachment, and cost gates all passed.
