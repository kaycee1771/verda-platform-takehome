# Assessor Access Instructions

**Status:** The Phase 5 Argo boundary is live and verified. Trusted TLS, SNI, and hostname checks
pass through all three protected ingress addresses; anonymous access is denied; administrator and
read-only reviewer authentication pass. Named SSH administration and protected direct Kubernetes
access remain available from approved sources. Do not add address values, source CIDRs, private
keys, session values, administrator kubeconfigs, or recovery material to this file.

## Access principles

- Public repository documentation contains service and role names, not operational address values
  or secrets.
- Credentials are delivered out of band and expire after the assessment window.
- Every assessor account is least privilege and independently revocable.
- Administrative APIs use an allowlist or SSH tunnel where practical.
- A scripted access check confirms reachability without exposing credentials.

## Endpoint inventory

| Service | URL or tunnel | Public port | Assessor role | Credential delivery | Expiry |
|---|---|---:|---|---|---|
| Demo application - dev | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Demo application - staging | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Demo application - prod | OPEN | 443 | Anonymous or test user | Not applicable | Assessment end |
| Rancher | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Argo CD | TLS URL supplied out of band | 443 | Read-only reviewer | Protected out-of-band session | Assessment end |
| Harbor | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Grafana | OPEN | 443 | Viewer | Out of band | OPEN |
| Kubernetes API | Redacted primary/direct paths | 6443 or SSH tunnel | Administrator path exists; assessor role pending | Out of band | 2026-08-24 |
| SSH | Redacted direct endpoint | 22 | `platform-admin`; source-restricted | Public key plus exact `/32` allowlist | 2026-08-24 |

Only the Argo CD platform-UI row is live; all other application and UI rows remain design contracts.
RKE2 is present. Public SSH, HTTP, HTTPS, and the protected Kubernetes API are the four accepted TCP
classes on each node. HTTP serves only ACME solver traffic and otherwise returns 404. Supervisor,
etcd, kubelet, Cilium/Hubble/metrics, and sampled NodePort classes remain denied. The independent
runtime verifier proved all four allowed and 28 denied classes on all three nodes without recording
address values. A genuinely independent non-allowlisted vantage remains a documented limitation.

## Verification flow

The Phase 3 host check is automated by `make verify-hosts CLUSTER=management`. Phase 4 adds
`make verify-cluster CLUSTER=management` for node, API, etcd, Cilium, networking, snapshots, CIS,
firewall, fault, stability, and diagnostics gates. Phase 5 adds the guarded `make bootstrap-gitops`
flow and the independent runtime verifier for exact Argo Applications, certificates, TLS, account
permissions, capacity, and the public boundary. These commands use external runtime material and
omit address and secret values from curated evidence.

The 2026-08-18 changed-source condition was recovered through the explicitly authorized
rollback-protected exact-source workflow. No broad temporary SSH rule was used. Protected primary
and direct-node administrator kubeconfigs stay in the ACL-restricted external directory and are
never distributed through Git. Argo administrator and reviewer sessions are also protected external
mode-`0600` files; the live verifier reads them only after unauthenticated and TLS gates pass. The
actual TLS URL and reviewer session are delivered out of band.

## Revocation

After the assessment, remove the administrator public key/account as part of teardown, revoke the
Cloud API credential, delete its operator-provided source image, remove external state/keys only
after required evidence retention, and destroy infrastructure through the guarded teardown phase.
Revoke or rotate the Argo administrator and reviewer sessions at handoff expiry. Later phases must
add robot, DNS, and service-account revocation steps when those resources exist.
