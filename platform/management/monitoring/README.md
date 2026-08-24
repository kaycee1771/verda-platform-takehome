# Monitoring

Argo CD reconciles the pinned `kube-prometheus-stack` release and its separate repository-owned
dashboards, monitors and alert rules. Prometheus and Alertmanager use Longhorn-backed storage;
Grafana is reached through the protected read-only port-forward described in `ACCESS.md`.

All required live targets are healthy. The synthetic alert verifies Prometheus-to-Alertmanager
transport, while `PlatformDemoUnavailable` is the bounded application availability rule.
