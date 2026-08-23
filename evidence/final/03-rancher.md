# Rancher

- Rancher workload pod Ready in `cattle-system`.
- Git-owned source: `platform/management/rancher/`.
- TLS certificates `rancher-staging` and `rancher-production`: Ready.
- External URL: `https://rancher.95-133-252-214.nip.io`.
- Authentication is required; direct Kubernetes access remains the recovery path.

Background Fleet operation jobs are transient and are not Rancher service replicas.
