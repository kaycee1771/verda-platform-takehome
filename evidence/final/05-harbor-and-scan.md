# Harbor and Trivy

- Harbor core, jobservice, registry, portal, exporter, PostgreSQL, Redis and Trivy: 8/8 pods Ready.
- Private project: `platform-demo`.
- Artifact digest: `sha256:1d48d05c8d4945fd891b07a865fcbdc7af459fa77adb75f9a88fd8ee0bfb289d`.
- Local pinned Trivy result: 0 HIGH, 0 CRITICAL.
- Harbor Trivy result: `scan_status=Success`, no severity findings.
- External health API returned HTTP 200.
- Namespace credentials are project-scoped pull-only robot credentials delivered outside Git.
