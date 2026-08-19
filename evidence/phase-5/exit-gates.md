# Phase 5 Exit Gates

Status: PASS.

| Gate | Result | Sanitized proof |
|---|---|---|
| Minimal pinned bootstrap | PASS | One Argo CD release plus one root Application; replay reached Helm revision 5 |
| Git owns day-one desired state | PASS | Exact one-root/eight-child set; 9/9 Healthy and Synced |
| Persistent storage | PASS | Dedicated disks 3/3; critical 4 MiB fixture preserved; replicas 3/3; cleanup absent |
| TLS | PASS | Staging-first then production; two certificates/issuers Ready; three ingress addresses verified |
| Authenticated management access | PASS | Anonymous denied; administrator and reviewer authenticated; reviewer read-only |
| Break-glass cluster access | PASS | Protected direct mode-`0600` kubeconfig works independently of ingress and Rancher |
| Exact external boundary | PASS | Three nodes; four allowed and 28 denied TCP classes per node |
| Capacity | PASS for Phase 5 | Positive one-node-loss CPU, memory, and worst-two-node storage headroom |
| Version/live compatibility | PASS | Locked Argo CD, cert-manager, and Longhorn artifacts verified in the live path |
| No Verda billable-resource expansion | PASS | No compute, volume, address, key, or object-storage resource added by Phase 5 |
| Final evidence-curated local `make ci` | PASS | 175 static tests and every canonical offline gate passed |
| Final protected hosted closeout CI | PASS | Run `32305521901`, job `96237316122` |

Phase 5 is complete. The phase map advances to 6 under the existing continuous
Phases 5–17 directive and Phase 6's own fail-closed prerequisites.

This file contains no address, resource identity, credential, session, kubeconfig,
certificate body, checksum value, or raw live payload.
