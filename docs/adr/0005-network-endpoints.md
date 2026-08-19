# ADR 0005: Use WireGuard and Explicit Public Endpoints on the Current Verda Surface

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Network and security architecture
- **Blocking gates:** GATE-007 closed by Phase 3 host-network evidence; Kubernetes endpoint gates remain Phase 4+

## Context

Blueprint Path A requires a private node network plus a supported HA API/ingress endpoint. Exact provider 1.1.2 exposes no private network, firewall/security group, load balancer, floating/VIP, or DNS resource. Installed CLI 1.8.1 has no command family for those services. The authenticated current-project navigation and deployment form expose no matching self-service controls. The provider computes a public instance `ip`, and current official instance guidance describes public-IP access.

RKE2 HA still requires a fixed registration address. A three-member etcd quorum does not make an external API endpoint highly available.

## Decision

Select blueprint **Path B** for this take-home:

- Assign each node its provider-managed public address and revalidate it after lifecycle operations.
- Establish a host-level WireGuard mesh before RKE2. Bind/route etcd, Kubernetes, Cilium, Longhorn, monitoring, and management internode traffic over stable WireGuard addresses.
- Permit WireGuard only between the three known public peers; restrict SSH to approved administrator/evaluator sources; do not expose Kubernetes internode ports directly.
- Use the primary node's WireGuard address on TCP 9345 as the **internal server-registration path**. Servers two and three never register through a public address, and public TCP 9345 remains denied.
- Use a designated primary node's public-address-derived `sslip.io` name as the **external default Kubernetes API path** on TCP 6443. Permit it only from the approved administrator source. Include the primary name, every direct-node name and address, and all WireGuard addresses in the TLS SAN contract.
- Generate protected direct-node break-glass kubeconfigs. Loss of the primary endpoint must not be described as loss of etcd quorum, but it does interrupt default-client access and new joins until a direct endpoint or replacement primary is selected.
- Run ingress on multiple nodes. Publish a primary evaluator URL plus documented direct-node alternatives; DNS round robin without health checking is never called a managed HA load balancer.

The exact public IPs, `sslip.io` names, WireGuard addresses, MTU, peer allowlist, and port matrix are generated only after Phase 2 and kept out of committed sensitive evidence where appropriate.

The immutable cluster ranges selected before first RKE2 start are:

| Purpose | CIDR |
|---|---|
| Management pods | `10.42.0.0/16` |
| Management services | `10.43.0.0/16` |
| Future workload pods | `10.44.0.0/16` |
| Future workload services | `10.45.0.0/16` |
| Management WireGuard underlay | `10.250.0.0/24` |

The controller-side LAN, WSL, VMware, and Docker route audit found no overlap on 2026-08-18. The
Phase 4 orchestrator repeats the comparison against current controller routes and every server's
main route table before installation. Any overlap blocks first start.

## Alternatives considered

- **Path A private network plus managed L4/floating endpoint:** preferred production pattern, unavailable on the inspected self-service surfaces.
- **kube-vip/Keepalived:** rejected without proven movable-address and shared L2/L3 semantics.
- **Unqualified public-IP mesh:** rejected because control-plane/storage traffic would be unnecessarily exposed.
- **DNS round robin called HA:** rejected because it has no health checking or guaranteed failover.
- **Single endpoint with no break glass:** rejected because endpoint loss would make recovery unnecessarily opaque.

## Consequences

- Control-plane data is encrypted between peers even though transport uses public infrastructure.
- Host firewall and WireGuard configuration become critical dependencies that require idempotent automation and rollback.
- The default registration/API endpoint is an explicit control-path SPOF. Direct-node access reduces recovery time but is not transparent failover.
- New-server registration depends on the designated primary's WireGuard endpoint. Default external clients depend on its public API name. These are separate failure paths even though they terminate on the same server.
- Public-IP replacement may require WireGuard peer, TLS SAN, DNS-fallback, inventory, and kubeconfig reconciliation.
- No claim of cloud-private networking, managed firewalling, managed endpoint HA, or regional isolation is permitted.

## Validation evidence

Phase 0 acceptance evidence is `evidence/phase-0/network-capability-surface.md`. Phase 3 evidence in
`evidence/phase-3/` proves three unique endpoints without recording their values, node-local
WireGuard identity, all six directed peer paths, authenticated handshakes, no-fragment MTU checks,
sustained traffic, the expected public allow/deny matrix, serial reboot survival, and strict
administrator recovery.

The 2026-08-18 Phase 4 preflight proved the exact-source control fails closed after an operator
address change: all three public SSH paths were denied before authentication. The owner then
authorized the rollback-protected exact-source reconciliation; a broad public exception was not
used.

The 2026-08-19 serial installation proves that servers two and three register through the primary
WireGuard supervisor path, common critical configuration is identical, all three nodes become
Ready, and internal Traefik routing succeeds on every node. The API is healthy inside the cluster.
The approved-source external API/negative scan and the controlled primary-endpoint failure drill
also passed: the default path failed as designed, the direct-node path and etcd quorum remained
available, and the default endpoint recovered. This proves the documented recovery path; it does
not turn the designated primary into a managed HA endpoint.

## Phase 3 outcome

The live underlay MTU is 1500 on all three nodes. The management WireGuard interface uses 1420 and
reserves 1370 for the later Cilium VXLAN layer. The exact overlay mapping and peer public endpoints
are generated only into ignored runtime files. ADR 0013 owns the hardened host, firewall, storage,
and recovery details.

## Production evolution

Use a managed health-checked L4 endpoint, private networking, managed firewall controls, and DNS automation across independent failure domains. Keep direct-node break glass but remove public exposure of control-plane internode ports.
