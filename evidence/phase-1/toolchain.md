# Phase 1 Toolchain Evidence

## Image identity

| Field | Value |
|---|---|
| Image | `verda-platform-quality:phase1-2026-08-16` |
| Local content digest | `sha256:6d32d1047025bce8bc6b4f3e0aa926c458ebef55ac486434c8d874aa38462bb0` |
| Size | 527,755,942 bytes |
| Runtime user | UID/GID `65532:65532`, non-login passwd entry |
| Validation network | Disabled |
| Cloud credentials forwarded | No |

The base image is pinned by multi-platform digest. Aqua 2.62.3 is downloaded with a locked archive
checksum. Bootstrap verifies that Aqua registry tag `v4.552.0` resolves to commit
`2dd9bbf64c7a550c0cbf45fabde630797efc001f`, and Aqua enforces package checksums.

## Exact version assertions

| Tool | Version | Tool | Version |
|---|---:|---|---:|
| Aqua | 2.62.3 | Terraform | 1.15.8 |
| TFLint | 0.64.0 | Trivy | 0.74.0 |
| Ansible Core | 2.21.3 | ansible-lint | 26.8.0 |
| yamllint | 1.38.0 | ShellCheck | 0.11.0 |
| Helm | 3.21.4 | kubectl | 1.35.7 |
| Kubeconform | 0.8.0 | Kyverno CLI | 1.18.2 |
| promtool | 3.13.2 | Gitleaks | 8.30.1 |
| pre-commit | 4.6.2 | PyMarkdown | 0.9.39 |
| Hadolint | 2.15.1 | actionlint | 1.7.12 |

All 18 assertions passed after the image build. Missing future-phase CLIs were reported as missing
and remain explicitly deferred in `versions.lock.yaml`; none was silently installed or represented
as implemented.

## Immutable input hashes

| Source | SHA-256 |
|---|---|
| `versions.lock.yaml` | `5861603e4c3c77afb15b4b75b4f98a916cfbe065654a357a793431c831621570` |
| `aqua.yaml` | `cd81f1a027341412374ca260f36682a343cdc087152d6adb7eb2e7634eba7845` |
| `requirements-quality.txt` | `c76bebfcc81740f1761a828dd4d44bb9eeccdf01a2e72a2fc39dae74b13274f1` |
| `schemas/schema-sources.lock.yaml` | `c8e902f402c7659def236a455d3c8b91161daf8340eb561c6abad6ed94a603af` |
| `tooling/quality/Dockerfile` | `610dc23b1b0c67b34d325e869215e9a081d9d96e0c9585b3d2f7d509169bfe4a` |
| Terraform provider lock | `4137cd8e6d51442cbf884a9c3b6318c7453ee0da63113396c47df31c9debb213` |

Bootstrap disables the default timestamped BuildKit attestation for this local validator image, so
identical content yields the stable digest above. Application build provenance remains mandatory in
Phase 6. The final isolated-clone tool-image report is 563 bytes with SHA-256
`1a502c6cdd21637072fb7f2d9fad946270cd7b1fe624c0963890ec845e154e7e`.

## Bootstrap implementation hashes

| Source | SHA-256 |
|---|---|
| `scripts/quality/bootstrap-tools.ps1` | `ba6008a15a891a7ec7a5bd561d10bb647cf8d443bc37ff2d31264060a9c18d65` |
| `scripts/quality/bootstrap-cache.sh` | `52dcf30437f4ed2b75699014dbe814ff1ed335dab5e694f790800c2f73deeb46` |
| `scripts/quality/bootstrap_schemas.py` | `c0abcef924783ed380f4c68bc7ec75a2e2b0b73e97f920fde2ff7433060bfea6` |
