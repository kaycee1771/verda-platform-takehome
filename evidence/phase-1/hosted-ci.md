# Phase 1 Hosted CI Evidence

## Successful run

- Repository: [`kaycee1771/verda-platform-takehome`](https://github.com/kaycee1771/verda-platform-takehome).
- Workflow: `Validate repository`.
- Run: [`31961790627`](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/31961790627).
- Job: `Credential-free quality gates`, job ID `95200750429`.
- Source commit: `751cd2e1d77d88d34a8afaf40e40683cc01e8a8e`.
- Event and runner: `push` on `main`, `ubuntu-24.04`.
- Result: PASS in 1 minute 33 seconds.
- Required stages: checkout, host prerequisites, safe cache restore, pinned bootstrap, complete
  positive and negative CI suite, report upload, and post-job cleanup all passed.

## Retained report artifact

Artifact `phase-1-quality-reports-31961790627` has GitHub artifact ID `9267440785`, was created at
2026-08-16T17:31:46Z, and expires after the configured seven-day retention on
2026-08-23T17:31:45Z. Codex downloaded it into ignored local storage and verified all nine files.

| Artifact file | Bytes | SHA-256 |
|---|---:|---|
| `gitleaks-history.json` | 3 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| `gitleaks-working-tree.json` | 3 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| `negative/generated-private-key.log` | 130 | `5d01af0870403f73f95d6fb68a60f597cf432645d020be7069dfa3d0da0f38b0` |
| `negative/invalid-alert-rule.log` | 255 | `e678a97febdebacdaf9b43437f4b7e30659655b05038840d9191ef03cd06456e` |
| `negative/invalid-kubernetes-object.log` | 288 | `92c6907c3c86ad54967a498f7721956d393b6dceb7ec416e4ef4bc266c421cd6` |
| `negative/malformed-terraform.log` | 389 | `4acc481b277315bc7eaf57ac2f0e53c6bc536177c8498aec315bef8f42875dce` |
| `negative/missing-custom-schema.log` | 171 | `625963bde56337aa609b8e1f2d97f75f8f45499ac332ec5cbd13e22567d09b39` |
| `negative/summary.txt` | 154 | `88a772b7b9849294a0f616dea014cbee017aea48b4231423d25a522abd8d9742` |
| `tool-image.json` | 446 | `5e7049df4bfb2153a44882498196f6a762a2612156954d31f3833570c032ebbf` |

Both Gitleaks JSON files contain only an empty array. The metadata confirms validation networking was
disabled, cloud credentials were not forwarded, and provenance used committed locks and checksums.

## Hosted-only failure and correction

Precursor run [`31959501564`](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/31959501564)
failed during bootstrap because Linux bind-mount ownership made the report directory unwritable by
host PowerShell. The correction retained non-root validation while granting only the runner owner
and validator group read/write access. The obsolete Node 20 artifact action was also replaced with
official v7.0.1 at immutable commit `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.

No cloud secret, Verda credential, kubeconfig, private key, or raw account response was present in
the workflow, logs, or artifact.
