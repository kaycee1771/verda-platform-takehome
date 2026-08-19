# Phase 4 Off-Cluster Snapshot Boundary

Status: RESOLVED on 2026-08-19 for the Phase 4 snapshot gate.

The 2026-08-18 check correctly blocked because this project did not expose the object-storage
entitlement documented by Verda. Support then enabled object storage for the existing project. The
repository owner explicitly authorized one manually created snapshot bucket and bounded access
credential because provider 1.1.2 exposes no Terraform resource for either object.

The live RKE2 acceptance check now proves a compressed, ready, positive-size recovery point in both
local and off-cluster S3-compatible location classes, with a creation timestamp, six-hour schedule,
and retention of eight in each class. Raw locations and credential values are absent from evidence.

The manual provider-gap ownership, credential boundary, reconciliation, and teardown obligations are
recorded in `manual-object-storage-exception.md`.

Official source: [Verda Object Storage CLI documentation](https://docs.verda.com/cli/object-storage/).
