# ADR 0005: Use Sealed Secrets for GitOps Secrets

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Security architecture

## Context

GitOps requires a safe representation for application secrets. Verda documentation reviewed for Phase 0 does not identify a managed secret store suitable for External Secrets Operator. Running Vault would add a high-consequence stateful control plane to the assessment.

## Decision

Use Sealed Secrets for environment application secrets. Bootstrap the controller through the platform path, store only encrypted SealedSecret resources in Git, and keep the controller recovery key outside the cluster and repository.

Use CI secret storage for build credentials such as the Harbor robot account. Do not force CI-only secrets into Kubernetes manifests.

## Alternatives

- **Plain Kubernetes Secrets:** rejected because base64 is not encryption and repository exposure is unacceptable.
- **CI variables rendered directly:** creates an imperative deployment path and weakens desired-state recovery.
- **SOPS with an Argo configuration-management plugin:** strong option, but increases Argo plugin and key-bootstrap complexity.
- **Vault plus External Secrets:** preferred in some production contexts, but too much state and operational scope for this take-home.

## Consequences

- Encrypted secret resources can participate in Git review.
- Controller key recovery becomes a critical backup requirement.
- Sealed Secrets does not provide dynamic credentials, leases, or a full external secret-manager trust boundary.

## Validation

- Secret plaintext does not appear in Git, Argo manifests, or CI logs.
- A sealed value is decrypted only by the cluster controller.
- Controller recovery keys are backed up and a recovery procedure is tested.

## Reversal triggers

- A supported external secret manager becomes available.
- Production requirements demand dynamic credentials or independent secret rotation.
