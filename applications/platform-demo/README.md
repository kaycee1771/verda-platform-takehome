# Platform demo application

This is the repository's canonical sample application and end-to-end platform acceptance
workload. Keeping the implementation, container build, Helm chart, and environment values in
one package avoids a second placeholder application boundary.

The Go service is dependency-free, deterministic, statically linked, non-root, and runs from
`scratch`. It exposes `/`, `/healthz`, `/readyz`, and `/metrics`; startup and request events are
JSON records on stdout with the stable `platform_demo` marker. The builder image must be passed
as an immutable digest. `scratch` is Docker's empty reserved base and has no mutable registry tag.

`chart/` is rendered once for each of `values-dev.yaml`, `values-staging.yaml`, and
`values-prod.yaml`. The final submission uses one controlled activation:

1. Verify the locked builder digest, build without network-dependent modules, test, scan, push
   once to Harbor, and record the resulting application digest.
2. Verify the staging Certificate for each exact `nip.io` hostname.
3. Install a namespace-owned `platform-demo-registry` Secret from the Harbor project-scoped,
   pull-only robot credential outside Git, and confirm the Prometheus Operator CRD.
4. Pin the resulting digest identically, set the gates, and reconcile dev, staging, then prod
   without rebuilding.

The immutable digest must be identical in all three value files. Dev and staging run one replica;
production runs two. The chart references the existing `platform-demo` ServiceAccount and its
`platform-demo-registry` pull Secret. It never owns or renders registry credentials.

The environment foundation already owns default-deny and DNS egress. This chart adds only the
two required ingress exceptions: Traefik to port 8080 and the monitoring Prometheus pod to the
same metrics port. The application needs no egress. Each release owns its namespaced Issuers,
Certificates, Deployment, ClusterIP Service, Ingress, ServiceMonitor, and these two policies.
