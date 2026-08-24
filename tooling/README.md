# Tooling

The quality image is the sole validator tool-delivery path for local runs and GitHub Actions.
`versions.lock.yaml` pins required versions and the immutable Aqua registry commit. Aqua consumes
the supported release ref, while bootstrap verifies that tag still resolves to the locked commit;
binary checksums remain mandatory. `requirements-quality.txt` pins Python dependencies.

Trivy is the canonical IaC scanner because one pinned engine covers Terraform, Kubernetes, and
Dockerfile misconfiguration without duplicating policy sources. Validation runs with no network,
all Linux capabilities dropped, a read-only container root, and no cloud credential mounts.

`make bootstrap-tools` is the only networked quality step. It builds the digest-pinned base image,
verifies upstream checksums, warms non-secret caches, and reports host tools without upgrading the
workstation. `make validate`, pre-commit, negative tests, and CI parity are offline.
GitHub Actions supplies its job-scoped, read-only `GITHUB_TOKEN` only to this bootstrap step. The
token is forwarded by name to the ephemeral cache container, used solely for allowlisted GitHub
Contents API requests, and is never persisted in the image, cache, reports, or command output.

The local validator build disables BuildKit's default timestamped provenance attachment so identical
inputs produce one stable image digest. Repository locks, upstream checksums, the verified Aqua
registry commit, and the tool-image report are its provenance record. Signed image provenance and
The application release evidence records the tested image, Trivy result and immutable digest.
