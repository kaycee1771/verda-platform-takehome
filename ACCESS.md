# Access Model

Phase 1 requires no Verda, Harbor, Kubernetes, DNS, or registry credentials. The quality container
receives only the repository mount and an explicit set of non-secret cache paths; validation runs
with networking disabled.

The future operator and reviewer access model is maintained in [docs/access.md](docs/access.md).
Credentials must be supplied out of band and must never be committed, copied into evidence, or
forwarded into credential-free CI jobs.
