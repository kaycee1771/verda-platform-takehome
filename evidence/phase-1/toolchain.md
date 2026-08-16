# Phase 1 Toolchain Evidence

## Image identity

| Field | Value |
|---|---|
| Image | `verda-platform-quality:phase1-2026-08-16` |
| Local content digest | `sha256:b37edda6b1fd2e5c2eb4d01564a86e7102af13433d8955cfbbfe0b821f3779a4` |
| Size | 527,756,798 bytes |
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

The ignored tool-image metadata report is 457 bytes with SHA-256
`eb215b219ed1b5b86c0e8b4648f3e9cf539b9daee38acd02b6181e20a6fb223c`.
