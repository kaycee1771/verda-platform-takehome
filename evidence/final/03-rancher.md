# Rancher

- Rancher workload pod Ready in `cattle-system`.
- Git-owned source: `platform/management/rancher/`.
- TLS certificates `rancher-staging` and `rancher-production`: Ready.
- External URL: `https://rancher.95-133-252-214.nip.io`.
- `/ping` returns successfully and the local cluster remains healthy.
- Dedicated evaluator local-user login is currently blocked by the upstream Rancher 2.14
  authentication defect. No password-hash, role or TLS workaround is accepted.
- The separately delivered short-lived read-only kubeconfig remains the bounded evaluator and
  recovery fallback.

Background Fleet operation jobs are transient and are not Rancher service replicas.
