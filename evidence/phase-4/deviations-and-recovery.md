# Phase 4 Deviations and Recovery

## Cilium L7 proxy traffic

The first complete Cilium connectivity run failed closed on L7, FQDN, TLS, and SNI paths while the
three-node cluster and Cilium agents remained healthy. Inspection showed that the host nftables
input hook evaluated before Cilium's proxy acceptance path and dropped Cilium TPROXY-marked pod
traffic.

The correction added one precise rule scoped to Cilium interfaces, the management pod CIDR, and
the proxy mark `0x0200`. It did not add a global forward accept, expose a public port, disable a
connectivity test, or weaken NetworkPolicy. The rerun completed the full connectivity suite and
removed all test namespaces.

## RKE2 S3 endpoint schema

The first snapshot command rejected a fully qualified endpoint URL. The RKE2 configuration was
corrected to store the endpoint authority expected by the pinned release while retaining TLS. The
on-demand snapshot then appeared in both local and off-cluster location classes.

## Cilium acceptance pressure and recovery history

The complete official functional lane is intentionally unfiltered, bounded to concurrency one, and
run with both Hubble and flow validation disabled. Pinned Cilium CLI v0.19.7 source confirms that
`--hubble=false` skips Relay-client and per-action flow collection, while `--flow-validation
disabled` bypasses flow-result validation. Functional test failures remain fatal. A separate
anchored pod-to-pod canary enables Hubble and strict flow validation through the localhost Relay
forward. The acceptance wrapper samples all nine per-agent/source lost-event counters immediately
before and after only that strict canary and rejects any positive delta. It also proves the exact
live DaemonSet rollout, bounded event-buffer capacity, Relay peer health, and kube-proxy boundary.
No upstream functional test is removed and no fatal outcome is converted to success.

The definitive bootstrap exposed that post-drill replacement of otherwise healthy Cilium-related
pods would erase expected restart history before the stability window. The current controller keeps
zero-restart reconciliation only before verification. After intentional node recovery it waits for
API, exact Cilium/Relay/operator readiness, and Cilium health without deleting pods; the stability
window then captures and holds the recovered identity/restart baseline.

## Residual closeout work

No Verda instance, volume, public address, or SSH-key resource changed. The definitive bootstrap's
drills, stability, idempotency, and support-bundle gates pass. The corrected current-tree independent
verification and final local quality also pass. Hosted CI remains pending. Phase 5 live mutation is
gated on the protected Phase 4 baseline.
