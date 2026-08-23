# Sealed Secrets desired-state boundary

The controller chart owns its CRD, Deployment, RBAC, webhook, Services, and
controller-generated key Secret. The key Secret is never authored by Argo CD
and its contents must never enter this repository.

All repository SealedSecrets use the default `strict` scope. The object name
and namespace passed to `kubeseal` must exactly match the committed object.
The `cluster-wide` and `namespace-wide` annotations are prohibited.

The controller Application belongs at sync wave `-15`. The monitoring
Application owns `monitoring/` at wave `-2`, after Prometheus Operator CRDs
exist. Controller and CRD pruning must remain disabled; retirement is a
separate, reviewed recovery operation.

No encrypted fixture is fabricated offline. A live fixture may be committed
only after the controller certificate is fetched from the protected cluster
and the procedure in the recovery runbook produces namespace/name-bound
ciphertext without writing plaintext to Git.
