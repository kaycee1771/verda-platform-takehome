# Architecture Contract

## Delivery thesis

The implementation follows a two-stage strategy. Stage A proves every mandatory assignment link on the smallest credible HA control plane. Stage B is the staff-level target and starts only after Stage A is green, reproducible, secure, evidenced, and affordable.

This replaces the pre-blueprint baseline that treated one co-located cluster as the final take-home target. The change is explicit in ADR-0002; it is not a silent architectural drift.

## Stage A — guaranteed pass path

```mermaid
flowchart TB
    Developer["Developer"] --> Git["Git repository"]
    Developer --> CI["CI: test and build once"]
    CI --> Harbor["Harbor: scan, SBOM, sign, store"]
    CI -->|"digest update PR"| Git
    Git --> Argo["Argo CD"]

    subgraph Verda["Verda Cloud"]
        subgraph Management["verda-mgmt: three schedulable RKE2 server nodes"]
            Rancher["Rancher"]
            Argo
            Harbor
            Observability["Prometheus, Alertmanager, Grafana, Loki, Alloy"]
            Platform["cert-manager, Longhorn, Sealed Secrets, Kyverno, Velero"]
            Dev["demo-dev"]
            Staging["demo-staging"]
            Prod["demo-prod"]
        end
        ObjectStorage["Verda S3-compatible object storage"]
    end

    Argo --> Dev
    Argo --> Staging
    Argo --> Prod
    Harbor --> Dev
    Harbor --> Staging
    Harbor --> Prod
    Platform --> ObjectStorage
    Observability --> ObjectStorage
```

Stage A is a temporary co-location decision, not the claimed final production pattern. It is complete only when every mandatory acceptance row is green end to end.

## Stage B — staff-level gold target

```mermaid
flowchart TB
    Developer["Developer"] --> Git["Git repository"]
    Developer --> CI["CI: test, build once, scan, SBOM, sign"]
    CI --> Harbor["Harbor"]
    CI -->|"immutable digest PR"| Git
    Git --> Argo["Argo CD"]

    subgraph Verda["Verda Cloud"]
        subgraph Management["verda-mgmt: three RKE2 server nodes"]
            Rancher["Rancher"]
            Argo
            Harbor
            Central["Central Grafana and Loki"]
            MgmtRecovery["Management recovery controllers"]
        end

        subgraph Workload["verda-workload: three RKE2 server nodes"]
            Dev["demo-dev"]
            Staging["demo-staging"]
            Prod["demo-prod"]
            WorkProm["Local Prometheus and Alertmanager"]
            Alloy["Grafana Alloy"]
            Cilium["Cilium and Hubble"]
            WorkStorage["Longhorn and Velero"]
        end

        ObjectStorage["Verda S3-compatible object storage"]
    end

    Rancher --> Management
    Rancher --> Workload
    Argo --> Management
    Argo --> Workload
    WorkProm --> Central
    Alloy --> Central
    MgmtRecovery --> ObjectStorage
    WorkStorage --> ObjectStorage
```

### Stage B decision gate

Stage B may start only when Stage A is fully green; a clean rebuild needs no undocumented console work; CI-to-dev GitOps works; one alert and one log investigation have been tested; Git history is secret-clean; and remaining credit/time covers the second cluster with contingency.

## Failure domains and claims

| Layer | Permitted claim | Explicit boundary |
|---|---|---|
| Kubernetes control plane | Three embedded-etcd servers tolerate one server loss while quorum remains healthy | Requires a working fixed registration/API endpoint |
| Workload scheduling | Replicated workloads can reschedule when requests, PDBs, spread, and spare capacity permit | Three servers alone do not make applications HA |
| Storage | Longhorn can replicate data across nodes | Replication is not an application-consistent or off-cluster backup |
| External endpoint | Path B: designated public API/registration endpoint plus direct-node break glass and multi-node ingress | No managed LB, floating IP, private VIP, or health-aware DNS is exposed; the designated endpoint is an honest SPOF for default clients and new joins |
| Stage A management | Individual replicas can survive a node loss | A whole-cluster failure removes both management and workloads |
| Stage B management | Management and workload Kubernetes APIs/etcd are independent | Both clusters may still share a Verda region/account |
| Regional recovery | Not claimed | Two clusters in one region are not regional DR |

## Traffic and trust boundaries

| Flow | Source | Destination | Required control |
|---|---|---|---|
| Evaluator UI | Internet | Rancher, Argo CD, Harbor, Grafana | TLS, authentication, scoped reviewer account |
| Application traffic | Internet | Traefik and environment service | TLS and only approved routes |
| Node administration | Approved CIDRs or tunnel | SSH and optional Kubernetes API | Key auth, allowlist, no password/root login |
| Cluster internode | RKE2 nodes | etcd, API, kubelet, CNI, Longhorn | WireGuard overlay, public-IP peer allowlist, host firewall, and tested MTU |
| Artifact push | CI | Harbor | TLS and project-scoped push robot identity |
| Artifact pull | Workload cluster | Harbor | TLS, pull-only identity, digest references |
| GitOps | Argo CD | Git and cluster APIs | Read-only Git credential and scoped cluster credential |
| Logs/metrics | Workload cluster | Management observability | Internal encrypted/TLS route; no public Loki |
| Backups | RKE2/Velero/Loki/Longhorn | Off-cluster S3-compatible storage | Prefer separate Verda credentials if entitlement appears; otherwise use ADR-approved external S3 and document the exception |

## Ownership boundary

The detailed day-zero/day-one contract is in `docs/operations-model.md`. In summary: Terraform owns Verda infrastructure, Ansible owns hosts and RKE2, bootstrap installs only Argo CD plus the root Application, Argo CD owns in-cluster desired state, CI owns artifact production, and Git owns the auditable desired state and promotion history.

## Immutable cluster addressing

| Network | CIDR | Status |
|---|---|---|
| Management pods | `10.42.0.0/16` | Phase 4 selected; immutable after first start |
| Management services | `10.43.0.0/16` | Phase 4 selected; cluster DNS `10.43.0.10` |
| Future workload pods | `10.44.0.0/16` | Reserved for Stage B; not implemented |
| Future workload services | `10.45.0.0/16` | Reserved for Stage B; not implemented |
| Management node underlay | `10.250.0.0/24` | Phase 3 WireGuard mesh |

The four Kubernetes ranges are pairwise disjoint and do not overlap the current controller LAN,
WSL, VMware, or Docker networks. A fail-closed runtime check compares them with every current node
and controller route before the first RKE2 service start.

## Current implemented posture

Phase 2 created exactly three `CPU.4V.16G` instances and six attached NVMe volumes in `FIN-03`
through Terraform. The immutable Ubuntu 24.04 Minimal configuration UUID remains the live catalog
invariant; ADR 0012 documents why provider 1.1.2 receives its canonical API image type. State is
DPAPI-sealed outside Git with an independent encrypted backup; remote S3 state remains honestly
deferred because provider ownership and state locking remain unproven even though object-storage
entitlement now exists.

Phase 2 is green after an explicitly authorized, assertion-bounded replacement of server-02 compute
and its instance-owned OS disk. Its protected data volume retained the original identity and
creation timestamp. Three unique public endpoints, exact attachments, live cost, and zero drift
remain green.

Phase 3 now implements the host trust boundary from ADR 0013. All three nodes use the named
`platform-admin` account with pinned-host-key, key-only sudo access; root and password SSH fail. A
dedicated nftables table allows SSH only from the current approved `/32`, permits WireGuard UDP only
between exact peer endpoints, accepts overlay traffic only from exact overlay peers, and leaves all
future public application and Kubernetes ports closed. Five-minute rollback timers and fresh-session
proofs protect SSH and firewall transitions.

The host WireGuard mesh uses stable addresses in `10.250.0.0/24`, an MTU of 1420 over the measured
1500-byte public underlay, and a reserved future Cilium VXLAN MTU of 1370. Every one of the six
directed no-fragment paths, recent peer handshakes, and a sustained three-node traffic ring passed.
Each protected data volume is ext4-formatted only after full empty-media proof, mounted by UUID at
`/var/lib/longhorn`, and verified after all three nodes rebooted serially. Full post-reboot
convergence is zero-change. Provider 1.1.2 and CLI 1.8.1 still expose no managed private network or
HA endpoint, so Path B remains an explicit limitation rather than a cloud-private-network claim.

Phase 4 installed the exact RKE2 `v1.35.7+rke2r1` path on all three schedulable server/etcd nodes.
The primary started first; servers two and three joined serially through the WireGuard supervisor
path only after the preceding node and etcd state were healthy. One sanitized hash proves identical
common critical configuration across all servers without hashing secret values.

The live cluster uses Kubernetes `v1.35.7`, embedded etcd `v3.6.14-k3s1`, bundled Cilium 1.19.6,
and bundled Traefik 3.7.8. Cilium retains kube-proxy, uses VXLAN at the measured 1370-byte MTU, and
enables Hubble plus internal metrics. The acceptance design separates the complete unfiltered,
Hubble-disabled functional suite from one Hubble-enabled strict flow canary whose exact lost-event
window must remain zero. The source-controlled same-node, cross-node, ClusterIP, DNS, egress,
NetworkPolicy, internal Traefik, and MTU smoke tests pass.

RKE2 uses the CIS profile, its pinned generated sysctls, secrets encryption, bounded audit logging,
and restricted administrator kubeconfig permissions. A focused ten-check assessment passes on every
server while explicitly deferring OIDC identity controls. Compressed etcd snapshots run every six
hours with retention of eight locally and eight in the manually enabled off-cluster S3-compatible
target. Provider 1.1.2 cannot own that bucket or credential, so its lifecycle remains a documented
manual exception.

The default public API/registration design is still not a managed HA endpoint. Direct kubeconfigs
remain protected outside Git. The controlled non-primary and designated-primary drills plus the
approved-source external boundary scan passed. Those tests prove one-node quorum and the documented
direct-path recovery behavior, but do not promote the default endpoint to a managed HA service.

Phase 5 established the day-zero/day-one handoff. A pinned Helm bootstrap owns only Argo CD and one
root Application; the root owns an exact eight-child set, and all nine Applications were Healthy
and Synced on the protected live revision. cert-manager completed staging-first issuance before the
production certificate and Git-owned Argo ingress were admitted. Argo is served with consistent
trusted TLS through each of the three node addresses, anonymous access is denied, and the scoped
reviewer can read but cannot sync or invoke actions. Protected direct kubeconfig access remains the
Rancher-independent break-glass path.

Longhorn schedules only the three dedicated data disks. A three-replica critical fixture retained
its 4 MiB checksum and storage identities through deliberate pod rescheduling, and temporary test
resources were absent after cleanup. Post-install requests retain positive one-node-loss CPU and
memory headroom, but the CPU margin is only 0.065 cores; Phase 6 therefore remains fail closed until
its exact rendered capacity plan passes.
