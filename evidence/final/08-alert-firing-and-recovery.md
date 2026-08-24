# Alert Firing and Recovery

## Synthetic transport-path test

A temporary `SubmissionAlertPipelineTest` PrometheusRule used `vector(1)`, a 15-second group interval and 30-second `for` duration. This was only a transport-path test of Prometheus-to-Alertmanager delivery; it was not a platform health signal.

1. Prometheus evaluated the rule.
2. Alertmanager API reported one active `SubmissionAlertPipelineTest` alert.
3. The temporary rule was deleted.
4. Alertmanager API later reported zero matching alerts.

This proves the Prometheus-to-Alertmanager firing and recovery path without leaving test desired state behind.

## Meaningful platform-demo availability rule

`PlatformDemoUnavailable` is repository-owned and uses the actual ServiceMonitor target labels: job and service `platform-demo`, endpoint `http`, and namespaces bounded to `demo-dev`, `demo-staging`, and `demo-prod`. It fires only when every discovered `/metrics` scrape target for one environment remains down for two minutes, so Kubernetes liveness/readiness probe noise is excluded and a single healthy production replica keeps the service available.

Promtool unit coverage proves healthy, pending, firing in `demo-dev` only, and recovery while staging and production remain healthy. A live demonstration was not performed because the required read-only cluster access was unavailable; no firing evidence was manufactured and no application or temporary live resource was changed.
