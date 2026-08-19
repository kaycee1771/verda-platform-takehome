# Management Non-Primary Node Failure

Status: PASS on 2026-08-19.

The bounded drill stopped exactly one non-primary RKE2 server with the pinned release kill-all path.
While that server was unavailable, the Kubernetes API remained ready, the two surviving etcd
members retained quorum, Cilium remained Ready on both surviving nodes, and the replicated test
workload remained available.

The stopped service was restarted and the cluster returned to three Ready nodes, three healthy etcd
members, and the exact Ready Cilium/Hubble stack. Two-node loss was deliberately not tested. The
current controller preserves expected recovered restart history rather than deleting healthy pods;
the corrected current-tree independent verification exercised and passed that recovery contract.

Raw node addresses, pod identities, endpoints, and command output are not recorded here.
