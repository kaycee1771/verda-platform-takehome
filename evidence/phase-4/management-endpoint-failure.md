# Management Primary-Endpoint Failure

Status: PASS on 2026-08-19.

The bounded drill stopped only the designated primary and proved that the documented named default
endpoint became unavailable within the two-minute loss boundary. A protected direct-node API path
remained ready and the two surviving etcd members retained quorum.

After service restoration, the named default path, all three protected direct-node paths, three-node
membership, and the exact Ready Cilium/Hubble stack recovered. The current controller performs only
bounded readiness checks after recovery and preserves expected restart history for the subsequent
stability baseline; the corrected current-tree independent verification exercised and passed that
contract.

No endpoint, address, kubeconfig, certificate, or node-specific command output is recorded here.
