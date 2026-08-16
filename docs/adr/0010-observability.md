# ADR 0010: Use Per-Cluster Prometheus with Central Grafana and Loki/Alloy

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Observability architecture
- **Blocking gates:** Exact chart/image versions and Loki mode remain pending capacity/version review

## Context

The platform needs local failure detection, centralized evaluator visibility, and searchable structured logs without operating an unnecessary global metrics backend. Promtail is retired; Grafana Alloy is the supported collector direction.

## Decision

Deploy kube-prometheus-stack and Alertmanager locally in each cluster. Host central Grafana and Loki on the management cluster; configure both Prometheus data sources in Grafana. Use Alloy in each cluster for logs. Select Loki Monolithic or HA Monolithic based on measured Stage A capacity, and keep only low-cardinality labels.

## Alternatives considered

- **One central Prometheus scraping both clusters:** simpler but loses local monitoring during cross-cluster interruption.
- **Thanos/Mimir:** valuable at scale but unnecessary for take-home volume.
- **Promtail:** rejected because it reached end of life in 2026.
- **Loki distributed mode:** excessive operational surface for this workload.

## Consequences

- Monitoring remains local during cross-cluster loss; one Grafana gives consolidated review.
- Central Loki remains a management-cluster dependency and must not be publicly exposed directly.
- Request IDs stay structured fields rather than index labels to control cardinality.

## Validation evidence

All required targets must be up; dashboards must answer defined operational questions; a deliberate fault must correlate release metadata, tested alert firing/resolution, and LogQL investigation by request/time/version.

## Production evolution

Evaluate durable remote write via Mimir/Thanos, horizontally scalable Loki, independent observability failure domains, and formal SLO/error-budget governance.
