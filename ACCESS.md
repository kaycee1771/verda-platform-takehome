# Evaluator Access

Credentials are never committed. Read-only UI credentials and any time-bound operator material are delivered separately in the protected bundle `.local/submission/access-private.md`.

| Service | URL / port | Authentication | Evaluator access |
|---|---|---|---|
| Rancher | `https://rancher.95-133-252-214.nip.io` / 443 | Required; login exception | Service reachable; use read-only kubeconfig fallback |
| Argo CD | `https://argocd.95-133-252-214.nip.io` / 443 | Required | Read-only applications/revisions |
| Harbor | `https://harbor.95-133-252-214.nip.io` / 443 | Required | Read-only project, artifact, scan |
| Grafana | protected `kubectl port-forward` to `monitoring-grafana:80` | Required | Viewer dashboards only |
| Dev app | `https://platform-dev.95-133-252-214.nip.io` / 443 | Anonymous | `/`, `/healthz`, `/metrics` |
| Staging app | `https://platform-staging.95-133-252-214.nip.io` / 443 | Anonymous | Read-only HTTP access |
| Production app | `https://platform-prod.95-133-252-214.nip.io` / 443 | Anonymous | Read-only HTTP access |

Kubernetes API and SSH are restricted operator paths, not evaluator mutation interfaces. Do not synchronize Argo applications, change Harbor artifacts, modify Rancher resources, request new certificates, or run destructive Make targets. Credentials expire with the review window and are independently revocable.

Send separately to Verda: Argo reviewer credentials, Harbor project-viewer credentials, Grafana viewer credentials and the short-lived read-only kubeconfig used for the Rancher access fallback. A Rancher reviewer credential is marked unavailable until the local-user authentication defect is resolved. Private keys, Terraform state, administrator kubeconfigs, and robot push credentials are not part of evaluator access.

See [docs/access.md](docs/access.md) for verification and troubleshooting details.
