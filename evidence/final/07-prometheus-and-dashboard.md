# Prometheus and Dashboard

- Prometheus pod Ready with `platform-critical` priority.
- Grafana pod Ready.
- Required targets were healthy in the latest accepted live monitoring verification. A fresh exact
  target count was not recorded because the evaluator kubeconfig intentionally cannot create a
  Prometheus port-forward; stale counts are not repeated.
- The repository-owned platform overview dashboard is `platform/management/monitoring/resources/grafana-dashboard-platform.yaml`.
- Grafana access is protected through a viewer credential and port-forward.
