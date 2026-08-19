#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo '[FAIL] Root is required to inspect RKE2 snapshot metadata.' >&2
  exit 1
fi

kubeconfig=/etc/rancher/rke2/rke2.yaml
kubectl=/var/lib/rancher/rke2/bin/kubectl
common_config=/etc/rancher/rke2/config.yaml.d/10-common.yaml
snapshot_secret=rke2-etcd-snapshot-s3-config

grep -Fqx "etcd-snapshot-schedule-cron: '0 */6 * * *'" "${common_config}"
grep -Fqx 'etcd-snapshot-retention: 8' "${common_config}"
grep -Fqx 'etcd-snapshot-compress: true' "${common_config}"
s3_retention=$("${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get secret \
  "${snapshot_secret}" -o jsonpath='{.data.etcd-s3-retention}' | base64 --decode)
[[ "${s3_retention}" == 8 ]]

snapshots=$(/usr/local/bin/rke2 etcd-snapshot ls --output=json 2>/dev/null)
python3 -c '
import json, sys
document=json.load(sys.stdin)
items=document.get("items", [])
selected=[]
for item in items:
  spec=item.get("spec", {})
  if spec.get("snapshotName", "").startswith("phase4-acceptance"):
    selected.append(item)
assert selected, "the Phase 4 acceptance snapshot is absent"
locations=set()
for item in selected:
  spec=item.get("spec", {})
  status=item.get("status", {})
  location=spec.get("location", "")
  if location.startswith("file://"):
    locations.add("local")
  elif location.startswith("s3://"):
    locations.add("off-cluster-s3")
  assert spec.get("snapshotName", "").endswith(".zip"), "acceptance snapshot is not compressed"
  assert status.get("readyToUse") is True, "acceptance snapshot is not ready to use"
  size=status.get("size")
  assert size not in (None, "", "0"), "acceptance snapshot size is not positive"
  assert status.get("creationTime"), "acceptance snapshot has no creation timestamp"
assert locations == {"local", "off-cluster-s3"}, "local and off-cluster recovery points are both required"
print(json.dumps({
  "schema_version": 1,
  "status": "PASS",
  "snapshot_name_prefix": "phase4-acceptance",
  "locations_present": ["local", "off-cluster-s3"],
  "compressed": True,
  "ready_to_use": True,
  "positive_size": True,
  "creation_timestamp_present": True,
  "schedule": "every-six-hours",
  "local_retention": 8,
  "off_cluster_retention": 8,
  "raw_locations_recorded": False,
}, sort_keys=True))
' <<<"${snapshots}"
