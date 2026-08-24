# Assignment Acceptance Matrix

| Requirement | Implementation | Live verification | Evidence | Status |
|---|---|---|---|---|
| Kubernetes | Three RKE2 server/etcd nodes | 3/3 Ready; API readiness includes etcd | [cluster](../evidence/final/02-kubernetes-and-etcd.md) | PASS |
| Rancher | GitOps-managed Rancher | pod Ready; TLS and evaluator read-only login verified | [Rancher](../evidence/final/03-rancher.md) | PASS |
| Argo CD | protected-main root application | controller Ready; platform reconciliation checked | [Argo](../evidence/final/04-argocd.md) | PASS |
| Harbor and scanning | private Harbor project with Trivy | artifact scan Success; 0 HIGH/CRITICAL | [Harbor](../evidence/final/05-harbor-and-scan.md) | PASS |
| Monitoring | Prometheus, Alertmanager, Grafana | required targets healthy; dashboard source loaded | [monitoring](../evidence/final/07-prometheus-and-dashboard.md) | PASS |
| Alert test | controlled PrometheusRule | active in Alertmanager, rule removed, alert resolved | [alert](../evidence/final/08-alert-firing-and-recovery.md) | PASS |
| Central logs | Alloy -> Loki | collectors Ready; LogQL returned app records | [logging](../evidence/final/09-loki-log-query.md) | PASS |
| Environments | isolated dev/staging/prod | 1/1/2 replicas Ready; one digest | [digests](../evidence/final/06-environment-digests.md) | PASS |
| TLS/access | cert-manager and least-privilege roles | all exposed certificates Ready; app health 204 | [access](../ACCESS.md) | PASS |
| Reproducibility | Terraform, Ansible, Argo, CI | local validation and protected CI | [CI](../evidence/final/13-hosted-ci.md) | PASS |

## Supporting capabilities

Longhorn, Cilium, WireGuard, Sealed Secrets and Kyverno are operational. Velero desired state is retained but full namespace/PVC restore evidence is not part of this submission; regional DR and a second cluster are not implemented.
