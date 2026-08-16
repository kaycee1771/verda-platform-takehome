# Phase 1 Evidence

## Scope

This evidence covers the repository and quality system only. It proves deterministic tool
bootstrap, positive validation, adversarial rejection gates, pre-commit behavior, secret scanning,
and local parity with the GitHub Actions job. It does not claim any Verda, Kubernetes, GitOps,
registry, application, DNS, or recovery capability.

## Canonical reproduction

```powershell
make bootstrap-tools
make validate
make validate-negative
make pre-commit
make secret-scan
make ci
```

All validation targets ran in the pinned non-root quality image with `--network none`. Bootstrap was
the only networked step and downloaded only public tool, provider, policy, and schema artifacts.

## Evidence index

- `toolchain.md`: immutable inputs, image identity, and exact tool versions.
- `validation-summary.md`: positive-gate results and explicit not-applicable checks.
- `negative-quality-gates.md`: malformed-input rejection proof.
- `secret-scanning.md`: working-tree and complete-history Gitleaks results.
- `ci-parity.md`: local workflow parity and hosted-run boundary.
- `clean-clone.md`: isolated checkout proof.

## Sanitization

No raw bootstrap or validator transcript is committed. The ignored local transcripts were reviewed,
summarized, and identified by SHA-256. Reports contain no credential, account identifier, private
key, kubeconfig, token, or cloud response.
