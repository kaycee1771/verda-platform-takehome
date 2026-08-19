# Phase 4 Evidence

Status: PASS. The definitive guarded bootstrap passed the three-node RKE2 cluster, networking,
snapshot, all-node CIS, external firewall, controlled failure, support-bundle, active-cluster
idempotency, and 270-second stability gates. The corrected current tree also passed its independent
end-to-end verification cycle and final local `make ci`. PR and protected-main hosted CI also
passed, so Phase 4 is complete.

## Completed evidence

- `version-selection.md`: current official support, release, component, and checksum verification.
- `cidr-design.md`: immutable ranges and live controller/node route analysis.
- `live-preflight.md`: exact resource, drift, cost, state, access, host, and route boundary.
- `management-installation.md` and `common-config-parity.md`: staged installation and immutable
  configuration proof.
- `management-nodes.txt`, `management-etcd-health.txt`, and
  `management-cilium-connectivity.txt`: curated control-plane scalar evidence.
- `management-networking.md`: pod, service, DNS, egress, policy, Traefik, MTU, and cleanup proof.
- `management-snapshots.md`: local and off-cluster recovery-point proof.
- `management-cis-assessment.md`: focused ten-check result on every server.
- `management-firewall-scan.md`: approved-source three-node public-port boundary.
- `management-node-failure.md` and `management-endpoint-failure.md`: bounded one-node and
  designated-primary endpoint drills with complete recovery.
- `management-support-bundle.md`: allowlisted, bounded, secret-safe diagnostic archive proof.
- `stability-and-idempotency.md`: recovered-state stability and zero-change convergence proof.
- `independent-verification.md`: corrected current-tree end-to-end verification result.
- `manual-object-storage-exception.md`: documented provider-gap ownership and teardown boundary.
- `deviations-and-recovery.md`: failed-closed Cilium and S3 corrections.
- `repository-validation.md`: credential-free implementation and evidence-safety proof.
- `exit-gates.md`: current gate-by-gate Phase 4 result.

## Closure

- `hosted-ci.md`: reviewed-commit PR and protected-main hosted validation proof.

Raw logs, kubeconfigs, endpoints, credentials, token material, state, and support archives remain in
ignored or external protected storage. Curated evidence must not contain those values.
