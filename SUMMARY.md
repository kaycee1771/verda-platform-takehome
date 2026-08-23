# Verda Platform Summary

## What I built

A reproducible three-node RKE2/etcd platform on Verda Cloud. Terraform provisions three VMs and six volumes, Ansible hardens the hosts and converges RKE2, and Argo CD owns the in-cluster platform. The live stack includes Rancher, Harbor with Trivy, Prometheus/Alertmanager/Grafana, Loki with Alloy, Longhorn, cert-manager, Sealed Secrets, Kyverno, and one GitOps application in dev, staging, and production.

## What worked

- Three schedulable RKE2 server nodes are Ready and the API/etcd readiness path passes.
- Rancher manages the local cluster while direct kubeconfig access remains available.
- Argo CD reconciles the platform and environment applications from protected `main`.
- Harbor stores the private application artifact; both local and Harbor Trivy scans reported zero HIGH or CRITICAL findings.
- Dev, staging, and production run the same immutable digest: `sha256:1d48d05c8d4945fd891b07a865fcbdc7af459fa77adb75f9a88fd8ee0bfb289d`.
- Prometheus had 42 of 46 active targets up; a controlled alert reached Alertmanager and then resolved.
- Alloy forwards application logs to Loki and the final LogQL query returned records from the application namespaces.
- All evaluator-facing application certificates were Ready and each public `/healthz` endpoint returned HTTP 204.

## Tradeoffs

- One shared cluster minimizes cost and delivery time but shares management/workload failure domains.
- Production runs two app replicas; lower-criticality controllers use one replica to fit credible requests on the selected nodes.
- Address-derived `nip.io` DNS replaces managed DNS/load balancing.
- Sealed Secrets and the bundled Harbor database are appropriate here, not enterprise HA boundaries.

## Remaining limitations

No second workload cluster, regional disaster recovery, enterprise OIDC, managed load balancer, or external HA databases are implemented. Grafana is reached through a protected port-forward rather than a public ingress. Some Argo aggregate health views are conservative even where underlying deployments, certificates, and endpoints are healthy.

## Cost and review window

The live six-volume, three-instance footprint costs **$0.231645/hour** or **$5.559/day**. The last reconciliation showed approximately **$78.95** credit, about **14 days** at the current rate. Resources are time-bound for the evaluator window and should be destroyed or explicitly extended before expiry; exact timing is confirmed separately because provider expiry is not printed in committed evidence.
