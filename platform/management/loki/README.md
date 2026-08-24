# Loki

Argo CD reconciles Loki in single-binary mode with 72-hour retention on a 5 GiB
`longhorn-critical` claim. Loki is internal-only and Grafana is the authenticated query interface.
Alloy runs on the three nodes and forwards application logs under the admitted network policies.
