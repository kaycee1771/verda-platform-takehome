# Phase 6 namespace and priority prerequisites

This Application owns the eight new platform namespaces and three Stage A
PriorityClasses. Component charts must not create or adopt these Namespace objects.
Monitoring, logging, and Velero use privileged PSA enforcement because their selected
node-level collectors and backup agents require host access; restricted audit and warning
labels remain enabled. All other Phase 6 platform namespaces enforce the restricted profile.

The environment Namespace objects are owned separately under `environments/*/namespace`.
Those foundations remain excluded from the Argo root until each committed strict-scope
SealedSecret ciphertext is produced out of band and the complete capacity admission passes.
No registry credential or Sealed Secrets private key belongs in this repository.
