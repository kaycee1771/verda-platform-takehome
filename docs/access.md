# Assessor Access Instructions

**Status:** The Phase 4 management cluster is live. Named SSH administration works from the exact
approved sources, the API is healthy internally, and the approved-source external API/direct-path
plus negative port-boundary checks passed. Application, platform UI, and assessor access remain
future work. Do not add live endpoints, source CIDRs, private keys, administrator kubeconfigs, or
recovery material to this file.

## Access principles

- Public repository documentation contains endpoints and role names, not secret values.
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
| Argo CD | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Harbor | OPEN | 443 | Read-only assessor | Out of band | OPEN |
| Grafana | OPEN | 443 | Viewer | Out of band | OPEN |
| Kubernetes API | Redacted primary/direct paths | 6443 or SSH tunnel | Administrator path exists; assessor role pending | Out of band | 2026-08-24 |
| SSH | Redacted direct endpoint | 22 | `platform-admin`; source-restricted | Public key plus exact `/32` allowlist | 2026-08-24 |

All application and platform UI rows remain design contracts, not live endpoints. RKE2 is present;
public `9345`, etcd, kubelet, Cilium, metrics, HTTP/S, and NodePort allow rules remain absent. The
source-controlled external scan and corrected current-tree independent verification proved that
observed boundary from the approved source. A genuinely independent non-allowlisted vantage remains
a documented limitation.

## Verification flow

The Phase 3 host check is automated by `make verify-hosts CLUSTER=management`. Phase 4 adds
`make verify-cluster CLUSTER=management` for node, API, etcd, Cilium, networking, snapshots, CIS,
firewall, fault, stability, and diagnostics gates. Both commands use external runtime material and
omit endpoint or secret values from curated evidence.

The 2026-08-18 changed-source condition was recovered through the explicitly authorized
rollback-protected exact-source workflow. No broad temporary SSH rule was used. Protected primary
and direct-node administrator kubeconfigs stay in the ACL-restricted external directory and are
never distributed through Git. Later phases must add assessor identities, copy-paste-safe TLS URLs,
and independent login checks.

## Revocation

After the assessment, remove the administrator public key/account as part of teardown, revoke the
Cloud API credential, delete its operator-provided source image, remove external state/keys only
after required evidence retention, and destroy infrastructure through the guarded teardown phase.
Later phases must add reviewer, robot, DNS, and service-account revocation steps when those resources
exist.
