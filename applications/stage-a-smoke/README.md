# Stage A smoke application

This package is a deliberately separate Phase 6 acceptance workload. It does not modify or
activate the Phase 9 `applications/platform-demo` placeholder.

The Go service is dependency-free, deterministic, statically linked, non-root, and runs from
`scratch`. It exposes `/`, `/healthz`, `/readyz`, and `/metrics`; startup and request events are
JSON records on stdout with the stable `stage_a_smoke` marker. The builder image must be passed
as an immutable digest. `scratch` is Docker's empty reserved base and has no mutable registry tag.

`chart/` is rendered once for each of `values-dev.yaml`, `values-staging.yaml`, and
`values-prod.yaml`. All three committed value files are inert. A controlled activation is:

1. Verify the locked builder digest, build without network-dependent modules, test, scan, push
   once to Harbor, and record the resulting application digest.
2. Set `certificate.bootstrapEnabled=true` for one environment and verify the staging
   Certificate for its exact `sslip.io` hostname.
3. Confirm the namespace-owned `platform-demo-registry` SealedSecret and Prometheus Operator CRD.
4. Replace the application digest sentinel, set every gate and `activation.enabled=true`, and
   reconcile that environment. Repeat without rebuilding for staging and production.

The immutable digest must be identical in all three value files. Dev and staging run one replica;
production runs two. The chart references the existing `platform-demo` ServiceAccount and its
`platform-demo-registry` pull Secret. It never owns or renders registry credentials.

The environment foundation already owns default-deny and DNS egress. This chart adds only the
two required ingress exceptions: Traefik to port 8080 and the monitoring Prometheus pod to the
same metrics port. The application needs no egress. Each release owns its namespaced Issuers,
Certificates, Deployment, ClusterIP Service, Ingress, ServiceMonitor, and these two policies.
