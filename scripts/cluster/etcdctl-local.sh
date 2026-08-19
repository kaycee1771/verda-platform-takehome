#!/usr/bin/env bash
set -euo pipefail

crictl=/var/lib/rancher/rke2/bin/crictl
cri_config=/var/lib/rancher/rke2/agent/etc/crictl.yaml

mapfile -t containers < <("${crictl}" --config "${cri_config}" ps --name etcd --quiet)
if [[ "${#containers[@]}" -ne 1 || ! "${containers[0]}" =~ ^[0-9a-f]{12,64}$ ]]; then
  echo '[FAIL] Expected exactly one running local etcd container.' >&2
  exit 1
fi

exec "${crictl}" --config "${cri_config}" exec "${containers[0]}" \
  /usr/local/bin/etcdctl "$@"
