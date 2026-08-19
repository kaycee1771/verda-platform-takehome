# Platform Demo Application

This boundary is reserved for the Phase 9 Go application. No application behavior, dependencies,
container artifact, or Kubernetes workload is implemented before that phase.

Helm is the single canonical renderer. The `deploy/chart/` directory will become authoritative;
Kustomize is intentionally absent to prevent duplicate sources of truth.
