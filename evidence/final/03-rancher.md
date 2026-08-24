# Rancher

- Rancher workload pod Ready in `cattle-system`.
- Git-owned source: `platform/management/rancher/`.
- TLS certificates `rancher-staging` and `rancher-production`: Ready.
- External URL: `https://rancher.95-133-252-214.nip.io`.
- `/ping` returns successfully and the local cluster remains healthy.
- Clean-session evaluator login succeeds through Rancher's supported local-provider API.
- The evaluator can read the local cluster, three nodes, three application namespaces and their
  workloads. Secrets, create, update, patch, delete, exec and impersonation are denied.
- The old broken evaluator identity was removed only after the replacement passed these checks.
- The separately delivered short-lived read-only kubeconfig remains an optional verification path.

Background Fleet operation jobs are transient and are not Rancher service replicas.
