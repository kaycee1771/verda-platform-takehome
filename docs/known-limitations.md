# Known Limitations

| Limitation | Consequence | Current mitigation | Production improvement |
|---|---|---|---|
| Management and apps share one cluster | shared failure domain | 3-member etcd, replicated storage, Git desired state, snapshots | separate management/workload clusters |
| No managed load balancer or DNS | address-derived names and no health-aware VIP | three ingress nodes, `nip.io`, direct recovery path | managed DNS and HA load balancer |
| Dense CPU allocation | rollout jobs can wait for capacity | right-sized requests, priorities, serial changes | larger/dedicated worker pool |
| Harbor bundled database | not independently HA | persistent Longhorn volume and backup procedure | managed/external HA PostgreSQL |
| Grafana is not public | evaluator needs port-forward | read-only kubeconfig/viewer account | authenticated ingress/OIDC |
| Sealed Secrets is cluster-key based | recovery requires controller key | protected backup and Git ciphertext | external enterprise secret manager |
| Namespace isolation | weaker than separate production clusters | RBAC, PSA, Kyverno, default deny | separate clusters/accounts |
| Regional DR not tested | regional outage requires rebuild | Terraform, Ansible, Git, etcd snapshots | cross-region backups and rehearsed failover |
| Some Argo aggregate health is conservative | UI may say Progressing despite healthy children | verify deployments, certificates and endpoints directly | custom health checks/upstream fixes |
