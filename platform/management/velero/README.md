# Phase 6 Velero baseline

This subtree defines the offline baseline for Velero chart `12.1.0`, Velero
`1.18.1`, and the compatible AWS object-store plugin `1.14.0`. It is not a
restore-completeness claim and is not yet admitted to the Argo root.

The controller and CRDs belong to a chart Application at sync wave `-4`.
`resources/` is a separate post-controller Kustomize source at wave `-3`, so a
BackupStorageLocation or Schedule cannot race the Velero CRDs. The chart's
implicit BSL, VSL, Schedule, CRD-upgrade hook, and CRD-cleanup hook are disabled
to prevent duplicate ownership and destructive lifecycle surprises.

## Volume strategy

Stage A selects Velero filesystem backup with the Kopia uploader and one
node-agent per RKE2 node. The selected daily schedule opts its pod volumes into
filesystem backup and disables volume snapshots. There is deliberately no
VolumeSnapshotLocation: the AWS plugin supplies S3 object storage, while the
cluster's Longhorn volumes are not AWS EBS volumes. Longhorn replicas provide
node-loss availability; Kopia provides an off-cluster data copy. Neither proves
application consistency.

The node-agent and generated data movers are bounded to one operation per node.
Repository-maintenance and data-mover resources are explicit, including
ephemeral storage. Both generated workload types use the pre-existing
`platform-workload` non-preempting PriorityClass; the always-on node-agent uses
`platform-important`. Smaller limits may increase backup duration or cause an
out-of-memory failure, so Phase 13 must tune them from measured backup and
restore runs.

## Credential boundary

Git references only the pre-existing Secret `velero-management-s3`, key
`cloud`. No Secret object or credential value is owned here. The credential
must be unique to the management Velero prefix and permit only the required
list, read, write, multipart-upload, and delete operations. It must not reuse
the etcd, Loki, Terraform-state, Harbor, or Longhorn credential.

Create the credential file outside the repository with mode `0600` and the
provider-compatible two-line AWS profile. After validating its ACL and scope,
create the Secret without placing either value in command arguments:

```bash
kubectl --kubeconfig "${PROTECTED_KUBECONFIG}" --context "${EXPECTED_CONTEXT}" \
  -n velero create secret generic velero-management-s3 \
  --from-file=cloud="${PROTECTED_VELERO_CREDENTIAL_FILE}"
```

Never print, decode, copy into evidence, or commit the Secret. Rotation requires
a new protected file, an in-place Secret replacement through the approved
workflow, controller/node-agent restart, BSL revalidation, and a new isolated
backup test. Existing Kopia repository passwords and credentials must remain
available for historical restores until retention and restore obligations end.

## Fail-closed activation and recovery boundary

`activation-contract.yaml` stays `blocked` until all image digests have primary
registry provenance, the dedicated bucket/prefix and credential scope are
proven, TLS path-style list/write/read/delete behavior succeeds, the BSL reports
`Available`, a Kopia repository initializes, and aggregate Phase 6 capacity
admission passes. A broad Trivy or policy waiver is not an activation gate.

Safe status checks expose only scalars:

```bash
kubectl --kubeconfig "${PROTECTED_KUBECONFIG}" --context "${EXPECTED_CONTEXT}" \
  -n velero get backupstoragelocation management-s3 \
  -o jsonpath='{.status.phase}{"\n"}'
kubectl --kubeconfig "${PROTECTED_KUBECONFIG}" --context "${EXPECTED_CONTEXT}" \
  -n velero get schedule management-environments-daily \
  -o jsonpath='{.status.phase}{"\n"}'
```

A successful Schedule or BSL validation proves neither restore integrity nor
application consistency. Phase 13 must restore into an isolated namespace,
verify data checksums and object-store artifacts, measure RTO/RPO, exercise
credential/key recovery, and record component-specific consistency limits
before any end-to-end recovery claim.

The Phase 6 service account is not bound to `cluster-admin`. It has read-only
access to namespaces, persistent volumes, and CRD metadata. The chart defines
the read-only `velero-namespaced-backup-reader` ClusterRole but intentionally
does not create cross-namespace RoleBindings: the backup AppProject can target
only `velero`, and the environment namespaces are created at a later sync wave.
Each environment-foundation application must bind that ClusterRole to the
`velero` service account after its namespace exists. The Schedule remains
paused until all three bindings are proven. Phase 13 restore permissions must
be separately reviewed, time-bounded to the isolated restore scope, and removed
after the rehearsal.
