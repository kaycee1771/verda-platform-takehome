# Access Model

The three Phase 3 hosts are live and hardened, but their addresses, approved administrative source
CIDR, and dedicated administrator private key are intentionally excluded from Git and evidence. The
generated inventory is ignored; keys, pinned host identities, state, and runtime variables remain
outside the repository boundary. No assessor-facing host access is claimed.

Every SSH host fingerprint is pinned to the Phase 2 identity. The named `platform-admin` account has
key-based sudo; fresh-session verification passed before password and root SSH were disabled.
Independent probes prove named-key login succeeds and both prohibited modes fail. nftables accepts
new SSH only from the current exact administrator `/32` and rate-limits it. A five-minute automatic
rollback protected the transition; console recovery remains the out-of-band fallback.

To operate from a changed source address, do not bypass host-key validation or add a broad public
CIDR manually. Use console/recovery access, supply the new exact canonical `/32` through the ignored
runtime boundary, and rerun `make configure CLUSTER=management` so the rollback and fresh-session
proofs execute again. Cloud, Kubernetes, Harbor, DNS, and registry credentials are neither required
nor accepted by credential-free quality validation.

The future operator and reviewer access model is maintained in [docs/access.md](docs/access.md).
Credentials must be supplied out of band and must never be committed, copied into evidence, or
forwarded into credential-free CI jobs. RKE2, Kubernetes API, Rancher, Argo CD, Harbor, Grafana, and
application access do not exist yet.
