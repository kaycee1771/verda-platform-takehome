# ADR 0009: Use Sealed Secrets for Take-Home Runtime Secrets

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Security architecture
- **Blocking gates:** Exact controller version remains pending Phase 1 lock review

## Context

Runtime secrets must be declarative without plaintext in Git. No Verda-managed secret service suitable for External Secrets has been verified, and operating Vault would add a high-consequence stateful control plane.

## Decision

Use Sealed Secrets for Kubernetes runtime secrets and the CI provider secret store for CI-only credentials. Keep only encrypted SealedSecret resources in Git. Back up the controller private key encrypted outside the repository and test recovery. Use distinct cluster keys unless deliberately scoped otherwise.

## Alternatives considered

- **Plain Kubernetes Secret manifests:** rejected; base64 is not encryption.
- **SOPS plus Argo plugin:** strong but adds plugin/key bootstrap complexity.
- **Vault/External Secrets:** preferred for some production environments but disproportionate here without a managed backend.

## Consequences

- Argo can reconcile encrypted secret objects.
- The sealing private key becomes critical recovery material.
- Sealed Secrets does not provide dynamic leases or external rotation.

## Validation evidence

Repository/history scans must be clean; a sealed value must decrypt only in the intended cluster; wrong-cluster decryption must fail; encrypted key backup and recovery must be tested.

## Production evolution

Adopt External Secrets with a governed cloud/enterprise secret manager when dynamic credentials, centralized rotation, auditing, or separation of duties require it.
