# Alert Firing and Recovery

A temporary `SubmissionAlertPipelineTest` PrometheusRule used `vector(1)`, a 15-second group interval and 30-second `for` duration.

1. Prometheus evaluated the rule.
2. Alertmanager API reported one active `SubmissionAlertPipelineTest` alert.
3. The temporary rule was deleted.
4. Alertmanager API later reported zero matching alerts.

This proves the Prometheus-to-Alertmanager firing and recovery path without leaving test desired state behind.
