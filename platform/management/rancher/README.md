# Rancher desired state

This wrapper owns the pinned Rancher 2.14.3 Helm dependency and the Rancher-specific ACME and
ingress-policy resources. The platform namespace foundation owns `cattle-system`; no other
Application may own these certificate resources.

The safe activation sequence is:

1. With `rancher.enabled: false`, reconcile the ACME Issuer and Certificate only.
2. Verify that the certificate is `Ready` for the exact
   `rancher.95-133-252-214.nip.io` hostname.
3. Confirm the registry-resolved Rancher, audit-sidecar, and shell image digests already locked
   in `versions.lock.yaml`, then set both admission gates plus `rancher.enabled` to `true` in one
   reviewed change after capacity admission.

Enabling the dependency before either proof makes Helm rendering fail. The chart never renders a
bootstrap password or another credential. Rancher generates the initial bootstrap credential;
the operator retrieves and rotates it outside Git. Evaluator access must use a dedicated local user
with the global `user` role and local-cluster `read-only` role. Credentials are created and verified
outside Git. The direct read-only kubeconfig is the evaluator fallback while the Rancher 2.14
local-user login defect remains unresolved.

Rancher is exposed only through Traefik with the cert-manager-owned production Secret. The current
deployment runs one Rancher replica. The chart enables level-0 audit metadata and Prometheus
metrics; the repository-owned ServiceMonitor scrapes the internal metrics endpoint over verified
TLS.

The direct kubeconfig remains the break-glass path and is intentionally independent of Rancher.
The disabled upstream post-delete hook prevents an ordinary Git rollback from deleting Rancher
namespaces or data.
