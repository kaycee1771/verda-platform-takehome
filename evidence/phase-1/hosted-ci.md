# Phase 1 Hosted CI Evidence

## Successful run

- Repository: [`kaycee1771/verda-platform-takehome`](https://github.com/kaycee1771/verda-platform-takehome).
- Workflow: `Validate repository`.
- Run: [`31960237401`](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/31960237401).
- Job: `Credential-free quality gates`, job ID `95196984993`.
- Source commit: `f4848cfe9dc738cc2b0d9787b1e33ffb6ff57efe`.
- Event and runner: `push` on `main`, `ubuntu-24.04`.
- Result: PASS in 1 minute 44 seconds.
- Required stages: checkout, host prerequisites, safe cache restore, pinned bootstrap, complete
  positive and negative CI suite, report upload, and post-job cleanup all passed.

## Retained report artifact

Artifact `phase-1-quality-reports-31960237401` has GitHub artifact ID `9267053278`, was created at
2026-08-16T17:01:03Z, and expires after the configured seven-day retention on
2026-08-23T17:01:03Z. Codex downloaded it into ignored local storage and verified all nine files.

| Artifact file | Bytes | SHA-256 |
|---|---:|---|
| `gitleaks-history.json` | 3 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| `gitleaks-working-tree.json` | 3 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| `negative/generated-private-key.log` | 130 | `9d64922b976e2d30c198181e708b371fc0706c3d897606564be33ba98a0bb7b2` |
| `negative/invalid-alert-rule.log` | 255 | `e678a97febdebacdaf9b43437f4b7e30659655b05038840d9191ef03cd06456e` |
| `negative/invalid-kubernetes-object.log` | 288 | `92c6907c3c86ad54967a498f7721956d393b6dceb7ec416e4ef4bc266c421cd6` |
| `negative/malformed-terraform.log` | 389 | `4acc481b277315bc7eaf57ac2f0e53c6bc536177c8498aec315bef8f42875dce` |
| `negative/missing-custom-schema.log` | 171 | `625963bde56337aa609b8e1f2d97f75f8f45499ac332ec5cbd13e22567d09b39` |
| `negative/summary.txt` | 154 | `88a772b7b9849294a0f616dea014cbee017aea48b4231423d25a522abd8d9742` |
| `tool-image.json` | 446 | `ab698fd7ba6b507db41692e6ec369e3f6acaae2b3e06d5d58a6132b3a56d6d` |

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
