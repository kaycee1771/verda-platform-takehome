# Phase 2 pre-apply validation

- Date: 2026-08-17
- Terraform: 1.15.8
- Verda provider: 1.1.2
- Verda CLI: 1.8.1

Immediately before plan, the authenticated live preflight proved:

- zero pre-existing instances and block volumes;
- `CPU.4V.16G` on-demand capacity available in `FIN-03` at $0.0279/hour;
- immutable image ID `77edfb23-bb0d-41cc-a191-dccae45d96fd` mapped uniquely to
  `image_type=ubuntu-24.04` and Ubuntu 24.04 Minimal;
- $115.67 balance and zero initial burn;
- provider schema checksum and the 1.1.2 resource-only surface unchanged.

The complete credential-free `make ci` suite passed: formatting, initialization, validation,
TFLint, native Terraform mock tests, Trivy HIGH/CRITICAL scan, Ansible/YAML/Shell/Helm/Kubernetes/
Kyverno/Prometheus/Dockerfile/Actions/Markdown checks, six negative rejection tests, pre-commit,
and working-tree/full-history Gitleaks.

After the provider-runtime reconciliation and removal of the final redundant module input, a fresh
credential-free `make validate` also passed on 2026-08-17. It reported zero TFLint warnings, zero
Trivy HIGH/CRITICAL findings, one passing Terraform native test, all schema and policy fixtures
passing, and no secrets in either the working tree or the complete Git history.

The saved plan assertion admitted exactly:

| Resource type | Creates |
|---|---:|
| `verda_ssh_key` | 1 |
| `verda_instance` | 3 |
| `verda_volume` | 3 |

There were no updates, deletes, replacements, unallowlisted types, sensitive outputs, or credential
values in plan JSON. Cost enforcement calculated $0.23165/hour, $38.92 for 168 hours, and $44.75
including 15% contingency under the $45 hard gate.
