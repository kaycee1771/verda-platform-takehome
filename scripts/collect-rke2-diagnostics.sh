#!/usr/bin/env bash
set -euo pipefail

sanitize() {
  sed -E \
    -e '/(token|secret|password|authorization|client-key-data|access[_-]?key|credential)/Id' \
    -e 's#https?://[^[:space:]/]+#[REDACTED_ENDPOINT]#g' \
    -e 's#s3://[^[:space:]]+#[REDACTED_S3_LOCATION]#g' \
    -e 's#([[:alnum:]-]+\.)+verda\.storage#[REDACTED_ENDPOINT]#gI' \
    -e 's#verda-takehome-mgmt-etcd-[[:alnum:]-]+#[REDACTED_S3_LOCATION]#gI' \
    -e 's#[[:alnum:]-]+(\.[[:alnum:]-]+)*\.sslip\.io#[REDACTED_ENDPOINT]#g' \
    -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/[REDACTED_IP]/g' \
    -e 's/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/[REDACTED_ID]/g' \
    -e 's/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}/[REDACTED_ID]/g' \
    -e 's/\<[0-9a-fA-F]{16}\>/[REDACTED_ID]/g'
}

if [[ "${1:-}" == '--sanitize-stdin' ]]; then
  sanitize
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo '[FAIL] Run through the approved passwordless sudo boundary.' >&2
  exit 1
fi

output_dir="${1:-/var/tmp/verda-rke2-support}"
umask 077
install -d -m 0700 "${output_dir}"

kubeconfig=/etc/rancher/rke2/rke2.yaml
kubectl=/var/lib/rancher/rke2/bin/kubectl
etcdctl=/usr/local/libexec/verda-phase4/etcdctl-local

capture() {
  local name=$1
  shift
  { "$@" 2>&1 || true; } | sanitize >"${output_dir}/${name}.txt"
}

capture service-status systemctl status rke2-server.service --no-pager
capture recent-journal journalctl -u rke2-server.service --since=-30min --no-pager
capture nodes "${kubectl}" --kubeconfig "${kubeconfig}" get nodes -o wide
capture system-pods "${kubectl}" --kubeconfig "${kubeconfig}" -n kube-system get pods -o wide
capture api-ready "${kubectl}" --kubeconfig "${kubeconfig}" get --raw=/readyz?verbose
capture cilium-status /usr/local/bin/cilium status --kubeconfig "${kubeconfig}" --wait=false
capture memory free -h
capture disk df -hT
capture routes ip -4 route show
capture links ip -details link show
capture firewall nft --stateless list table inet verda_platform
capture snapshots /usr/local/bin/rke2 etcd-snapshot ls
capture secrets-encryption /usr/local/bin/rke2 secrets-encrypt status
capture certificates /usr/local/bin/rke2 certificate check --output table
capture audit-metadata stat -c '%a %U:%G %s %y %n' /var/lib/rancher/rke2/server/logs/audit.log

etcd_args=(
  --endpoints=https://127.0.0.1:2379
  --cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt
  --cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt
  --key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key
)
ETCDCTL_API=3 capture etcd-health "${etcdctl}" "${etcd_args[@]}" endpoint health --cluster
ETCDCTL_API=3 capture etcd-endpoints "${etcdctl}" "${etcd_args[@]}" endpoint status --cluster --write-out=table
ETCDCTL_API=3 capture etcd-members "${etcdctl}" "${etcd_args[@]}" member list --write-out=table
ETCDCTL_API=3 capture etcd-alarms "${etcdctl}" "${etcd_args[@]}" alarm list

find "${output_dir}" -type f -exec chmod 0600 {} +
echo "[PASS] Sanitized support bundle directory created: ${output_dir}"
