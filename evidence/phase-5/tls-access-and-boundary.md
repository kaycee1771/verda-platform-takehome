# Phase 5 TLS, Access, and External Boundary

Status: PASS.

The independent runtime verifier exercised every protected ingress address while
preserving address values outside Git. It verified SNI, hostname matching, trusted
issuer identity, certificate dates, and an identical public leaf certificate at
all three addresses.

| Gate | Sanitized result |
|---|---:|
| cert-manager ready replicas | 6 |
| Ready certificates / issuers | 2 / 2 |
| TLS ingress addresses verified | 3 |
| Anonymous Argo API access | denied on 3/3 |
| Administrator authentication | PASS |
| Reviewer authentication and read | PASS |
| Reviewer sync/action | denied |
| HTTPS root response | 200 on 3/3 |
| Plain HTTP root response | 404 on 3/3 |
| Plain HTTP ownership | ACME solver only |
| Nodes scanned | 3 |
| Allowed TCP port classes per node | 4 |
| Denied TCP port classes per node | 28 |

The production issuer and public ingress were admitted only after the staging
certificate path succeeded. RKE2-owned Traefik remains the only ingress
controller. The exact allowed public classes are SSH, HTTP, HTTPS, and the
protected Kubernetes API; supervisor, etcd, kubelet, Cilium/Hubble/metrics, and
sampled NodePort classes remain denied by the source-controlled boundary.

Certificate bodies, fingerprints, dates, issuer payloads, addresses, account
sessions, kubeconfigs, and raw scan output remain outside Git.
