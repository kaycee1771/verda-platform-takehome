# Prometheus and Dashboard

- Prometheus pod Ready with `platform-critical` priority.
- Grafana pod Ready.
- Active scrape targets: 46; healthy targets: 42.
- Four targets were associated with the demo namespaces during the live query.
- The repository-owned platform overview dashboard is `platform/management/monitoring/resources/grafana-dashboard-platform.yaml`.
- Grafana access is protected through a viewer credential and port-forward.
