# Phase 2 recovery and exit gates

## Authorized recovery

The user explicitly authorized replacement of only `verda-mgmt-server-02` and its instance-owned
80 GiB OS disk while preserving `verda-mgmt-data-02`. The canonical recovery plan and apply targets
both required `CONFIRM=--confirm` and `CONFIRM_DESTRUCTIVE_ACTION=yes`.

Before state correction, the seven-address state audit and an independently located DPAPI backup
passed. The sanitized saved-plan assertion reported:

- mode `node-02-replacement`;
- exactly one `delete/create` action and one `verda_instance`;
- only `verda-mgmt-server-02`;
- `CPU.4V.16G`, FIN-03, on-demand, Ubuntu 24.04, and an 80 GiB NVMe OS disk;
- the exact before/after persistent data-volume attachment unchanged;
- no credential values and no sensitive outputs; and
- SHA-256 `bbae1b085ac4f375db7677fe8f85fde1510ce613e497be652453775df042f42d`.

The saved plan applied successfully. Backups were verified immediately before and after mutation.

## Verification corrections

The first post-repair host check failed closed because Terraform's stored output still held the old
address. The live Verda API already reported three unique endpoints. A refreshed plan proved zero
resource actions and its no-op apply persisted only the refreshed outputs.

The next SSH attempt exposed an argument-mode quoting bug in the PowerShell verifier: the remote
`hostname` expression was evaluated locally. The read-only retry loop was interrupted, the command
was constructed as a literal remote expression, and a local regression assertion proved it remained
literal. The corrected verifier then passed all three hosts. No cloud resource changed during either
verification correction.

## Final exit-gate results

| Gate | Result |
|---|---|
| Exact 3 instances, 3 OS volumes, 3 protected data volumes, 1 SSH key | PASS |
| Three unique public endpoints | PASS |
| Exact data-volume attachment per instance | PASS |
| Dedicated-key SSH and expected remote hostname on all three nodes | PASS |
| Deterministic ignored three-host Ansible inventory | PASS |
| Full destroy rejected by `prevent_destroy` | PASS |
| Compute rollback bounded to exactly three instance deletions | PASS |
| Live resource count and $0.23165/hour burn reconciliation | PASS |
| Final Terraform resource plan has zero changes | PASS |
| Seven-address state audit and independent encrypted backup | PASS |

The final no-drift plan SHA-256 was
`b8f563e99d2f1eff2dedd202b75cd2ddc9e12c71d844a9bb1cb3237d1617dc69`. Resource IDs, public IPs,
credential values, private key material, state, and plan binaries are intentionally absent.

After the final live audit, both credential environment variables were removed and the authenticated
shell was terminated. The time-bound credential object remains subject to its account expiry and
teardown revocation control.

Six credential-free unit cases additionally prove that the recovery assertion accepts the exact
replacement and rejects an extra resource, wrong address, update-only action, changed persistent
volume, or changed machine image.

The final complete `make ci` run passed after live recovery: repository and exact-version contracts,
the six recovery unit cases, Terraform format/validate/native tests, warning-free TFLint and Ansible
production-profile lint, zero HIGH/CRITICAL Trivy findings, YAML/Shell/Helm/Kubernetes/Kyverno/
Prometheus/Dockerfile/Actions/Markdown gates, six invalid-input rejection fixtures, pre-commit, and
repeated working-tree/full-history Gitleaks scans.
