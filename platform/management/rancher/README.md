# Rancher

This wrapper owns the pinned Rancher 2.14.3 Helm dependency and the Rancher-specific ACME and
ingress-policy resources. The platform namespace foundation owns `cattle-system`; no other
Application may own these certificate resources.

The chart uses locked images and fails closed unless its certificate and admission inputs are
present. It never renders a bootstrap password or another credential. Rancher credentials are
created and rotated outside Git through supported server-side paths.

The dedicated evaluator has the global `user` role, a bounded local-cluster read-only role and
namespace-scoped workload visibility. Clean login and explicit Secret/mutation denial are verified
by `bootstrap/cluster-registration/register-rancher.sh verify`.

Rancher is exposed only through Traefik with the cert-manager-owned production Secret. The current
deployment runs one Rancher replica. The chart enables level-0 audit metadata and Prometheus
metrics; the repository-owned ServiceMonitor scrapes the internal metrics endpoint over verified
TLS.

The direct kubeconfig remains the break-glass path and is intentionally independent of Rancher.
The disabled upstream post-delete hook prevents an ordinary Git rollback from deleting Rancher
namespaces or data.
