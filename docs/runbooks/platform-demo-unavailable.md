# Platform Demo Unavailable

## Impact

The `platform-demo` metrics endpoint is unreachable for every discovered replica in one of the bounded demo environments.

## Immediate checks

Confirm the alert namespace, then inspect the `platform-demo` Deployment, Service endpoints, pod readiness, ServiceMonitor target and the exact Prometheus ingress NetworkPolicy. Do not change staging or production while diagnosing a dev-only alert.

## Safe remediation

Restore the repository desired state through Argo CD. Do not disable TLS, authentication, NetworkPolicy or reconciliation, and do not leave a live patch behind.

## Recovery validation

Require at least one healthy `platform-demo` scrape target in the affected namespace, the Deployment available, and the alert absent from Prometheus and Alertmanager.
