# Upgrade Strategy

1. Open a pull request changing `versions.lock.yaml` and the single matching tool or chart source.
2. Verify the proposed version and compatibility matrix against the vendor's official documentation.
3. Regenerate checksums or schema locks only from immutable release references.
4. Rebuild the quality image and run `make ci` from a clean clone.
5. For platform components, exercise backup, restore, rollback, and version-skew gates before promotion.
6. Record the evidence and decision in the changelog and, for architecture changes, an ADR.

Automated dependency updates are deferred until the core platform works. No script upgrades the
candidate's workstation automatically.
