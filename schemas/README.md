# Schema Sources

`schema-sources.lock.yaml` is the source of truth for the Kubernetes 1.35 and custom-resource
schemas used by Kubeconform. Bootstrap downloads only HTTPS sources pinned by release or commit,
verifies every source checksum, and derives schemas into the ignored `.local/schema-cache/`.

Every supported custom kind/version has a positive fixture. Missing schemas remain fatal and are
proved by the negative quality-gate suite; global schema bypasses are prohibited.
