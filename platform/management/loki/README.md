# Loki Phase 6 desired-state boundary

This directory defines chart `7.3.0` with Loki `3.6.12` in `SingleBinary`
mode. Exactly one Loki replica and one internal gateway are planned. Every
Simple Scalable and Distributed replica group, both caches, MinIO, the canary,
chart tests, the rule sidecar, and the rollout operator are disabled.

S3-compatible object storage is the log system of record. The retained 5 GiB
Longhorn claim contains only the Loki WAL, compactor, and working state; it is
not a filesystem log backend. Loki expands endpoint, region, bucket names, and
credentials from the pre-existing `loki-object-storage` Secret at runtime.
This repository never owns or contains that Secret's values.

Retention is 72 hours and Compactor deletion is delayed by two hours. Any
bucket lifecycle safety net must be at least seven days so it cannot race the
index-aware Compactor. The three bucket names must be unique and must not use
the upstream defaults `chunk`, `ruler`, or `admin`.

Loki is internal-only: gateway ingress is disabled, services are `ClusterIP`,
and the chart network policies allow same-namespace traffic, monitoring reads,
DNS, and TLS egress for the external object store. Grafana is the authenticated
query interface.

## Fail-closed activation

`activation-contract.yaml` is intentionally `blocked`. The listed image digests have
authoritative registry provenance, but do not create or enable an Argo Application
until the dedicated S3 scope and lifecycle have passed a
live read/write/delete compatibility test, and the full Phase 6 capacity gate
passes. Changing only `activation_status` is insufficient; every Boolean gate
must be true and the locked values must contain the verified digests.

The controller belongs at sync wave `-6` in namespace `loki`, matching the
pre-provisioned Grafana data-source URL. Alloy remains in `logging`. Deletion or
replacement of the external buckets is not an Argo lifecycle operation.
