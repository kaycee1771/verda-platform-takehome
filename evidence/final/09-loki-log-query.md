# Loki Log Query

- Loki and gateway: 2/2 pods Ready.
- Alloy: 3 desired/current/Ready/available collectors.
- Query: `{namespace=~"demo-(dev|staging|prod)"}` over the preceding 30 minutes.
- Result: 4 streams and 92 entries.
- Namespaces returned: `demo-dev`, `demo-staging`, `demo-prod`.

The final fix retained cluster-wide Kubernetes pod discovery and allowed the API backend port only through the existing Cilium `kube-apiserver` entity policy.
