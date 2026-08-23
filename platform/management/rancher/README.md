# Rancher desired state

This wrapper owns the pinned Rancher 2.14.3 Helm dependency and the Rancher-specific ACME,
PodDisruptionBudget, and ingress-policy resources. The Phase 6 namespace foundation owns
`cattle-system`; no other Application may own the PDB or these certificate resources.

The safe transition is deliberately two-stage:

1. With `rancher.enabled: false`, reconcile the staging Issuer and Certificate only.
2. Verify that `rancher-staging` is `Ready` for the exact `rancher.*.sslip.io` hostname.
3. Confirm the registry-resolved Rancher, audit-sidecar, and shell image digests already locked
   in `versions.lock.yaml`, then set both admission gates plus `rancher.enabled` to `true` in one
   reviewed change after capacity admission.

Enabling the dependency before either proof makes Helm rendering fail. The chart never renders a
bootstrap password or another credential. Rancher generates the initial bootstrap credential;
the operator retrieves and rotates it outside Git. The account reconciler uses only the protected
direct management kubeconfig, creates separate `platform-admin` and `verda-reviewer` local users,
and assigns the reviewer the built-in cluster `read-only` role.

Rancher is exposed only through Traefik with the cert-manager-owned production Secret. Its three
replicas use required hostname anti-affinity and an independently owned PDB with `minAvailable: 2`.
The chart enables level-0 audit metadata and Prometheus metrics. A ServiceMonitor belongs to the
later monitoring-resource wave so the Rancher Application never races the Prometheus CRDs.

The direct kubeconfig remains the break-glass path and is intentionally independent of Rancher.
The disabled upstream post-delete hook prevents an ordinary Git rollback from deleting Rancher
namespaces or data.
