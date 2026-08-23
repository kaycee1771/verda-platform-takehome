# Sealed Secrets key recovery and rotation

## Impact

Loss of every controller private key prevents new reconciliation of existing
SealedSecrets after cluster rebuild. It does not expose ciphertext and it does
not replace a centralized production secret manager.

## Preconditions

- Use only the protected management kubeconfig and verify its exact context.
- Work from an ACL-restricted temporary directory outside the repository.
- Use a version-pinned `kubeseal` client matching controller 0.38.1.
- Use a separately managed, approved encryption recipient. Never store its
  private identity, passphrase, or recovery output in Git or shell history.
- Record operator, UTC time, reason, cluster identity, and recovery-object
  checksum without recording secret data.

## Strict sealing procedure

1. Fetch the controller certificate from the protected cluster into the
   restricted temporary directory.
2. Build a Kubernetes Secret with `kubectl create secret --dry-run=client` and
   supply every value through standard input or a protected temporary file.
3. Pipe the Secret directly to `kubeseal` with all of:
   `--scope strict`, `--namespace <exact-namespace>`,
   `--name <exact-secret-name>`, and the fetched certificate.
4. Commit only the resulting SealedSecret. Confirm it contains neither
   `data`, `stringData`, plaintext values, nor broad-scope annotations.
5. Reconcile and verify only Secret name, namespace, type, key names, and
   workload readiness. Never print decoded values.

## Encrypted key backup

1. Select Secrets bearing
   `sealedsecrets.bitnami.com/sealed-secrets-key=active` in the
   `sealed-secrets` namespace.
2. Stream their YAML directly into the approved encryption tool. The encrypted
   destination must be outside the repository with access limited to recovery
   custodians.
3. Record the encrypted file checksum, controller version, cluster identity,
   key Secret names, backup time, and custodians in the external recovery
   inventory. Do not record Secret data.
4. Remove any plaintext temporary material and prove it is absent before the
   terminal session ends.

## Recovery rehearsal

1. Create an isolated rehearsal cluster or approved recovery namespace. Never
   overwrite the healthy production key during a test.
2. Decrypt the backup only inside an ACL-restricted temporary directory.
3. Restore the key Secret with its original namespace, name, labels, and data.
4. Start controller 0.38.1 and apply a namespace/name-strict, non-sensitive
   fixture sealed by the restored public certificate.
5. Prove reconciliation and record only sanitized object status and checksum
   evidence.
6. Destroy the rehearsal objects and plaintext workspace; prove absence.

## Rotation

The controller creates a new sealing key every 720 hours. Old keys remain for
decrypting existing SealedSecrets. After a new key is active:

1. Fetch the new certificate.
2. Re-encrypt each repository SealedSecret with `kubeseal --re-encrypt` and
   submit the ciphertext-only changes for review.
3. Verify every object reconciles before considering old-key retirement.
4. Create and verify a new encrypted external recovery backup.
5. Delete an old key only under a separately approved destructive procedure
   after repository-wide resealing and rollback evidence are complete.

## Escalation

Stop immediately if the protected context is wrong, the backup cannot be
decrypted, any broad-scope annotation appears, plaintext reaches a tracked
path, or a private key may have been exposed. Treat exposure as compromise and
rotate affected runtime credentials after key recovery.
