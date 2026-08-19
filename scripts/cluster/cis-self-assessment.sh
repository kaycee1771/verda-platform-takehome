#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo '[FAIL] Root is required to inspect RKE2-managed files and processes.' >&2
  exit 1
fi

pass=0
fail=0
check() {
  local description=$1
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS | %s\n' "${description}"
    ((pass += 1))
  else
    printf 'FAIL | %s\n' "${description}"
    ((fail += 1))
  fi
}

check 'CIS profile selected' grep -Eq '^profile:[[:space:]]+cis$' /etc/rancher/rke2/config.yaml.d/10-common.yaml
check 'traditional etcd principal exists' getent passwd etcd
check 'RKE2 CIS sysctls installed' test -s /etc/sysctl.d/60-rke2-cis.conf
audit_policy_mode=$(stat -c %a /etc/rancher/rke2/audit-policy.yaml)
check 'audit policy exists and is restricted' test "${audit_policy_mode}" -le 600
kubeconfig_mode=$(stat -c %a /etc/rancher/rke2/rke2.yaml)
check 'administrator kubeconfig is group-restricted' test "${kubeconfig_mode}" -eq 640
check 'API anonymous authentication disabled' grep -Eq 'anonymous-auth=false' /etc/rancher/rke2/config.yaml.d/10-common.yaml
check 'API profiling disabled' grep -Eq 'profiling=false' /etc/rancher/rke2/config.yaml.d/10-common.yaml
check 'secrets encryption active' bash -c '/usr/local/bin/rke2 secrets-encrypt status | grep -q "Encryption Status: Enabled"'
check 'audit log active and nonempty' test -s /var/lib/rancher/rke2/server/logs/audit.log
check 'RKE2 service active' systemctl is-active --quiet rke2-server.service

printf 'SUMMARY | pass=%d fail=%d\n' "${pass}" "${fail}"
printf '%s\n' 'WARN | CIS 1.12 manual identity controls remain: Phase 4 uses break-glass client certificates; OIDC is deferred to the Rancher identity phase.'
printf '%s\n' 'WARN | This focused RKE2 1.35 self-assessment does not claim independent certification or replace the SUSE CIS 1.12 guide.'
((fail == 0))
