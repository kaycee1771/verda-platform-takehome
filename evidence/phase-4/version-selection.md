# Phase 4 Version Selection

Verified on 2026-08-18 immediately before implementation.

The guarded installation on 2026-08-19 consumed the checksum-pinned artifacts without selecting a
floating channel or alternate version. The resulting three-node cluster passed its node, system-pod,
etcd, Cilium, and network verification gates.

| Contract | Verified value | Authoritative source |
|---|---|---|
| Rancher compatibility | Rancher 2.14.3 certifies RKE2 1.33–1.35 | [SUSE Rancher support matrix](https://www.suse.com/suse-rancher/support-matrix/all-supported-versions/rancher-v2-14-3/) |
| RKE2 | `v1.35.7+rke2r1`; stable, non-draft, non-prerelease; published 2026-08-04 | [Official release](https://github.com/rancher/rke2/releases/tag/v1.35.7%2Brke2r1) |
| Operating system | Ubuntu 24.04 supported for RKE2 1.35 | [SUSE RKE2 1.35 matrix](https://www.suse.com/suse-rke2/support-matrix/all-supported-versions/rke2-v1-35/) |
| Kubernetes | `v1.35.7` | Official RKE2 release and SUSE matrix |
| etcd | `v3.6.14-k3s1` | Official RKE2 release and SUSE matrix |
| Cilium | `v1.19.6`, bundled chart `1.19.601` | Official RKE2 release |
| Traefik | `v3.7.8`, bundled chart `40.1.009` | Official RKE2 release |
| Cilium CLI | `v0.19.7`, stable release | [Official Cilium CLI release](https://github.com/cilium/cilium-cli/releases/tag/v0.19.7) |

The official `sha256sum-amd64.txt` release asset supplied the RKE2 tar checksum. The installer
source is pinned to tag commit `382a8b31a8fd78e376ab6f02c4bb0ec5592aada2` and hashed for
provenance, but is not executed. The role downloads and verifies the exact tar artifact directly.
Exact checksums and chart archive hashes are recorded once in `versions.lock.yaml` and consumed by
Ansible variables; no floating channel is used.

The pinned RKE2 Cilium chart also supports the source-controlled agent `RollingUpdate` strategy with
`maxUnavailable: 1` and Hubble `eventBufferCapacity: "8191"`. The acceptance contract keeps the
complete unfiltered Cilium CLI functional suite at concurrency one with Hubble and flow validation
disabled, followed by an anchored Hubble-enabled strict flow-validation canary. The exact v0.19.7
[CLI flags](https://github.com/cilium/cilium-cli/blob/v0.19.7/vendor/github.com/cilium/cilium/cilium-cli/cli/connectivity.go),
[Hubble client gate](https://github.com/cilium/cilium-cli/blob/v0.19.7/vendor/github.com/cilium/cilium/cilium-cli/connectivity/check/context.go),
and [disabled-validation path](https://github.com/cilium/cilium-cli/blob/v0.19.7/vendor/github.com/cilium/cilium/cilium-cli/connectivity/check/action.go)
support that separation. Runtime verification fails closed unless the DaemonSet rollout, effective
buffer setting on all three agents, kube-proxy compatibility mode, Relay peer health, and exact
per-agent/source zero lost-event delta across the strict-canary window match the contract. These
configuration and acceptance changes do not alter any pinned version.

Configuration decisions were checked against the current official [server configuration
reference](https://docs.rke2.io/reference/server_config), [HA guide](https://docs.rke2.io/install/ha),
[CIS hardening guide](https://docs.rke2.io/security/hardening_guide), [network
requirements](https://docs.rke2.io/install/requirements), [Cilium integration](https://docs.rke2.io/networking/basic_network_options),
and [backup/restore guide](https://docs.rke2.io/datastore/backup_restore).
