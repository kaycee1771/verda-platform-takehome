# Phase 6 namespace and priority prerequisites

This Application owns the eight new platform namespaces, three Stage A
PriorityClasses, and the `cattle-system` container-default LimitRange. The
LimitRange is applied after the Namespace and before Rancher; its bounded
100m/128Mi request and 500m/256Mi limit cover the upstream Rancher pre-upgrade
hook, whose chart exposes no resource settings. Component charts must not
create or adopt these prerequisite objects.
Monitoring, logging, and Velero use privileged PSA enforcement because their selected
node-level collectors and backup agents require host access; restricted audit and warning
labels remain enabled. All other Phase 6 platform namespaces enforce the restricted profile.

The environment Namespace objects are owned separately under `environments/*/namespace`.
Those foundations remain excluded from the Argo root until each committed strict-scope
SealedSecret ciphertext is produced out of band and the complete capacity admission passes.
No registry credential or Sealed Secrets private key belongs in this repository.
