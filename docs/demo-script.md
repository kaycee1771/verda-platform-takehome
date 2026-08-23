# Ten-Minute Demo

## 0–1 — Architecture

Show [architecture](architecture.md): one three-node RKE2 cluster, GitOps ownership, and the cost/time tradeoff. Mention the separate-cluster production evolution briefly.

## 1–2 — Kubernetes and Rancher

Show three Ready nodes and API readiness, then Rancher with the local cluster Active. Mention the protected direct kubeconfig recovery path.

## 2–4 — GitOps and environments

Show Argo CD, the platform root and environment applications. Show dev/staging/prod deployments and the identical image digest.

## 4–5 — Harbor

Open the private `platform-demo` project, the immutable artifact, and its successful Trivy report.

## 5–7 — Monitoring and logging

Open the platform Grafana dashboard and a `platform_demo` metric. Show the controlled alert firing/resolution evidence. Run the documented Loki query and show structured application records.

## 7–8 — Security and storage

Show restricted pod security/default-deny policy, Ready certificates, Longhorn nodes/volumes and dedicated disks.

## 8–9 — Reproducibility

Explain Terraform/Ansible/Argo ownership. Show `make validate` and the protected read-only `make verify`.

## 9–10 — Cost and limitations

Show the $0.231645/hour rate, review window, teardown plan, shared-cluster limitation and production evolution.
