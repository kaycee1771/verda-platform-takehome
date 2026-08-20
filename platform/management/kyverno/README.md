# Kyverno Phase 6 boundary

Kyverno 1.18.2 is installed through the 3.8.2 chart in deliberately
fail-open, Audit-first mode. The admission controller has two replicas and a
PodDisruptionBudget. Background and reports controllers remain enabled; the
unused cleanup controller is disabled to preserve capacity.

The controller chart owns CRDs, controllers, webhooks, RBAC, and metrics
Services at sync wave `-12`. `monitoring/` is a distinct wave `-2` ownership
boundary because ServiceMonitor resources must not race Prometheus Operator
CRDs. `policies/kyverno/base` and reviewed exceptions are also wave `-2`.

Phase 6 must not change any policy to `Enforce`. A future transition requires
the Phase 12 compatibility tests, violation inventory, rollback procedure, and
explicit authorization.
