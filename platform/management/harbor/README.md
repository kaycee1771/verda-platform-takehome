# Phase 6 Harbor baseline

This subtree is intentionally split into three independently owned Helm releases:

1. `secrets/` owns only seven `SealedSecret` resources. It cannot render until every
   ciphertext is produced out of band and the ciphertext gate is explicitly enabled.
2. `postgresql/` owns a single PostgreSQL 15.10 StatefulSet, Service, PVC contract, and
   database NetworkPolicy. It consumes the Secret produced by the first release.
3. `service/` wraps the checksum-locked Harbor 1.19.2 chart (Harbor 2.15.2), owns the
   public certificate and Harbor NetworkPolicies, and consumes only existing Secrets.

The coordinator must wire these as distinct Argo CD Applications in the order above at
wave `-8`; no Application may adopt an object owned by another one. The `harbor`
Namespace and `platform-important` PriorityClass remain cluster-prerequisite ownership.
The Prometheus wave owns the eventual ServiceMonitor because Harbor must not race the
Prometheus CRDs.

## Fail-closed activation

The committed state is deliberately inert. Activation requires all of the following in
reviewed changes:

- create the seven secret payloads locally, seal them for the `harbor` Namespace, replace
  every `REQUIRED_SEALED_CIPHERTEXT_*` sentinel, and enable `secrets/`;
- confirm the locked official PostgreSQL image manifest digest, attest that the database Secret
  reconciled, and enable `postgresql/`;
- first reconcile the Harbor staging certificate and verify it for the exact hostname;
- confirm all eight locked Harbor image digests from the audited 2.15.2 image set, attest that
  Secrets and PostgreSQL are Ready, then enable the Harbor dependency.

No chart value contains a password. Harbor receives admin, database, encryption,
jobservice, registry, htpasswd, XSRF, and token-signing material exclusively from existing
Secrets. `bootstrap-private-projects.sh` receives the admin and reviewer passwords only
through the environment, creates the private `platform-demo` project, enables automatic
scanning and SBOM generation, and grants `verda-reviewer` the Harbor guest role. It never
creates a public project or an anonymous push path.

## Availability, persistence, and peak model

This is a capacity-conscious Platform baseline, not a claim of database HA. Longhorn
protects blocks against a storage-node loss, but PostgreSQL, Valkey, registry, jobservice,
and Trivy each have one application replica. A node loss therefore causes bounded
application downtime while Kubernetes and Longhorn reschedule. Production would use an
external HA PostgreSQL service and object storage for registry blobs.

| Owner/workload | Replicas | Request (CPU/memory) | Limit (CPU/memory) | PVC | Storage class | Rollout peak |
|---|---:|---:|---:|---:|---|---:|
| PostgreSQL | 1 | 200m / 384Mi | 1 / 1Gi | 8Gi | longhorn-critical | 1 pod; same ordinal replacement |
| Harbor core | 1 | 150m / 256Mi | 1 / 1Gi | none | n/a | 2 during rolling update |
| Harbor portal | 1 | 25m / 64Mi | 200m / 128Mi | none | n/a | 2 during rolling update |
| Harbor jobservice | 1 | 75m / 128Mi | 500m / 512Mi | 2Gi | longhorn-standard | 1; Recreate for RWO |
| Registry + registryctl | 1 pod | 125m / 256Mi | 750m / 768Mi | 20Gi | longhorn-critical | 1; Recreate for RWO |
| Valkey | 1 | 50m / 128Mi | 250m / 256Mi | 2Gi | longhorn-critical | 1 pod; same ordinal replacement |
| Trivy adapter | 1 | 200m / 512Mi | 1 / 1Gi | 10Gi | longhorn-standard | 1 pod; same ordinal replacement |
| Harbor exporter | 1 | 25m / 64Mi | 200m / 128Mi | none | n/a | 2 during rolling update |

Steady state is 850m CPU and 1.792Gi memory requested across Harbor and PostgreSQL.
The controller's capacity admission gate must include this complete request/PVC model and
the rolling peak before the Applications are activated. Singleton PDBs are intentionally
disabled: a `minAvailable: 1` PDB on a one-replica stateful service would block voluntary
maintenance without adding availability.

## Network and TLS boundaries

The public endpoint is Traefik-only and references the cert-manager-owned production TLS
Secret. Kubernetes default-deny policies are paired with component-specific ingress and
egress: DNS, exact Harbor service ports, PostgreSQL, Valkey, and Prometheus scraping.
Trivy's only Internet egress is TCP/443 to its declared vulnerability-database OCI hosts,
expressed as a Cilium FQDN policy. PostgreSQL has no egress and accepts only Harbor core
and exporter traffic. Harbor internal traffic is HTTP inside the namespace in this
bounded baseline; it is isolated by policy. External client traffic is always HTTPS.

## Operations

Use `bootstrap-private-projects.sh preflight` for read-only checks, `reconcile` only with
both mutation guards, and `verify` after reconciliation. Harbor being unavailable must
not remove direct Kubernetes access; use the protected management kubeconfig for
break-glass diagnosis. Preserve all PVCs and database backups during rollback. Git revert
is the configuration rollback; destructive data rollback is a separately authorized
recovery operation.
