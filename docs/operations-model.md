# Operations Model

| Layer | Owner | Change method | Recovery authority |
|---|---|---|---|
| Verda infrastructure | Terraform | reviewed saved plan; explicit apply | protected state and backup |
| Ubuntu hosts / RKE2 | Ansible | serial convergence and idempotency check | rebuild plus etcd snapshot |
| Kubernetes desired state | Argo CD | reviewed Git merge | Git revert/reconciliation |
| Application artifact | CI and Harbor | test, build once, scan, push digest | previous immutable digest |
| Runtime credentials | operator / secret controller | out-of-band or encrypted manifest | rotate/reseal |

## Promotion

`make promote FROM=dev TO=staging DIGEST=sha256:...` updates only the target environment value. Review the diff, merge it, and let Argo reconcile. Repeat from staging to production with the same digest. Rollback is the same process using the previously accepted digest; no rebuild occurs.

## Routine verification

Use `make validate` for repository checks, `make status` for a concise read-only inventory, `make verify` for protected live verification, `make collect-evidence` for sanitized reports, and `make cost-report` for rate reconciliation. Destructive operations require an explicit plan and confirmation.
