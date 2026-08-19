# Management Stability and Idempotency

Status: PASS for the definitive bootstrap on 2026-08-19.

The post-drill stability gate captured the recovered kube-system pod identities and restart counts,
then observed ten samples over 270 seconds. All three nodes remained Ready; pod identities and
restart counts remained unchanged; and the API, etcd, and Cilium remained healthy.

The active-cluster preparation replay completed on all three servers with zero changes, zero
unreachable hosts, and zero failures. This proves convergence of the preparation path without
claiming that a live cluster should erase expected restart history.

The corrected current controller now waits for exact post-drill readiness without replacing healthy
Cilium, Relay, or operator pods, then lets this stability gate establish the recovered baseline. An
independent corrected-current-tree verification reran and passed that path.
