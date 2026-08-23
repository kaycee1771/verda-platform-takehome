# Network and Security

- All evaluator-facing certificates queried were Ready.
- Workload namespaces use restricted Pod Security Admission and Kyverno baseline policy.
- Environment and service network policies are default deny with explicit DNS, ingress, monitoring, registry and API flows.
- Harbor permits pull-only application credentials; anonymous push is not enabled.
- SSH is key-only and source restricted; Kubernetes administration is a protected operator path.
- No credentials, state, kubeconfig, key or raw Secret is stored in this evidence set.
