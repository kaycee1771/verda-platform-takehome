# Threat Model

## Phase 1 scope

The assets in scope are source integrity, version locks, validation evidence, Git history, and the
developer workstation boundary. There is no live platform or cloud trust boundary in this phase.

## Primary threats and controls

| Threat | Phase 1 control |
|---|---|
| Secret committed in current files or history | Gitleaks scans both surfaces with redacted output. |
| Supply-chain drift | Exact tool versions, immutable image digest, Aqua registry tag, and checksummed downloads. |
| CI action retagging | Every external action is pinned by full commit SHA. |
| Cache poisoning | CI caches only non-secret validator/provider data under a lock-file-derived exact key. |
| Schema bypass | Kubeconform strict mode has no global missing-schema override. |
| Validation exfiltration | Validation runs with networking disabled and receives no host credential variables. |
| False confidence from placeholders | Future commands stop non-zero behind explicit phase gates. |

## Deferred boundaries

Cloud identity, node access, cluster PKI, registry trust, GitOps credentials, and backup encryption
are modeled and tested in their owning later phases. Their repository locations exist but contain no
working configuration in Phase 1.
