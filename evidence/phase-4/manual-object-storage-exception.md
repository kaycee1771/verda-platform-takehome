# Manual Object-Storage Exception

Status: RESOLVED for the Phase 4 snapshot gate on 2026-08-19.

## Why an exception was required

The pinned Verda Terraform provider exposes no object-storage bucket or access-key resource. The
project initially lacked object-storage entitlement, so the earlier preflight correctly blocked
off-cluster snapshot acceptance rather than inventing a provider resource or substituting
in-cluster storage.

Verda support subsequently enabled object storage for the existing project. The repository owner
explicitly authorized creation of one Phase 4 snapshot bucket and a bounded access credential
through the authenticated console. This is a documented provider-capability exception, not an
undocumented desired-state path.

## Reconciliation and security

- The region and S3-compatible endpoint schema were verified against the enabled project surface.
- Credential values remained in the ACL-restricted external credential store and process
  environment; they were not printed, copied into command arguments, committed, or included in
  evidence.
- RKE2 proved one compressed acceptance snapshot in both local and off-cluster location classes.
- The manual bucket and credential require explicit inventory, rotation, and deletion during
  teardown because Terraform cannot own their lifecycle in provider version 1.1.2.

No raw endpoint, bucket, key label, object path, or credential value is recorded here.
