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

## Current implemented posture

Phase 2 created exactly three `CPU.4V.16G` instances and six attached NVMe volumes in `FIN-03`
through Terraform. The immutable Ubuntu 24.04 Minimal configuration UUID remains the live catalog
invariant; ADR 0012 documents why provider 1.1.2 receives its canonical API image type. State is
DPAPI-sealed outside Git with an independent encrypted backup; remote S3 state remains honestly
deferred because object-storage entitlement and locking are unproven.

Phase 2 is green after an explicitly authorized, assertion-bounded replacement of server-02 compute
and its instance-owned OS disk. Its protected data volume retained the original identity and
creation timestamp. Three unique public endpoints, exact attachments, dedicated-key SSH with remote
hostname assertions, compute-only rollback, live cost, and final zero drift all pass. No host
configuration, networking, RKE2, or Phase 3 action has started. Provider 1.1.2 and CLI 1.8.1 still
expose no private network, firewall/security group, load balancer, floating/VIP, or DNS resources,
so ADR 0005 Path B remains the intended later network path.
