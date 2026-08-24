# Access and Verification

Public URLs and roles are listed in [../ACCESS.md](../ACCESS.md). Secret values are delivered separately and never copied into evidence.

## Expected checks

- Rancher: authenticate with the separately delivered evaluator account; inspect the local cluster,
  nodes, namespaces and workloads. Secrets and mutation are denied.
- Argo CD: authenticate read-only; inspect revisions, sync and health; do not press Sync.
- Harbor: authenticate project-viewer; inspect `platform-demo/platform-demo`, immutable digest and Trivy report.
- Grafana: use a protected port-forward and viewer account; open the platform overview dashboard.
- Applications: each HTTPS `/healthz` returns 204.

## Protected operator paths

The Kubernetes API uses a hostname-bound kubeconfig and the direct API endpoint. SSH is key-only, source-restricted and intended only for recovery/operations. Neither path is required for normal evaluator UI access. If a credential expires, issue a new least-privilege credential; never reuse administrator or robot push credentials.

The private evaluator handoff is delivered outside Git with owner-only permissions.
