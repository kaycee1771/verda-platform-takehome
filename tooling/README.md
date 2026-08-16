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
