# Evidence: Current Network Capability Surface

- Collected: 2026-08-16
- Scope: exact provider 1.1.2 schema, installed CLI 1.8.1 help, authenticated current-project navigation, and instance deployment form
- Mutation: none

| Capability | Provider resource | CLI command family | Current project link/field | Result |
|---|---|---|---|---|
| Provider-managed public instance address | Computed `verda_instance.ip` | VM describe after creation | No user-selectable address field | Supported/automatic; lifecycle untested |
| Private node network | None | None | None | Not exposed |
| Firewall/security group | None | None | None | Not exposed |
| Managed L4 load balancer | None | None | None | Not exposed |
| Floating/virtual public IP | None | None | None | Not exposed |
| Private VIP suitable for kube-vip | None | None | None | Not exposed |
| DNS resource/control | None | None | None | Not exposed |

The console check searched current project links and deployment lines for network, firewall, security group, load balancer, floating, virtual IP, VIP, and DNS; it returned no matches. This is a scoped statement about current self-service surfaces, not every Verda commercial offering.

## Architecture consequence

ADR-0005 accepts blueprint Path B: public instance addresses, host WireGuard for internode traffic, a designated `sslip.io` API/registration endpoint, protected direct-node break-glass kubeconfigs, and ingress on all nodes. The primary endpoint is not called HA.

## Evidence still required after provisioning

- Sanitized public-IP and route inventory.
- WireGuard peer, MTU, throughput, and restart tests.
- Host-firewall allowed/denied port matrix.
- Primary RKE2 registration and direct-node API checks.
- Multi-node ingress reachability.
- Primary-endpoint failure/recovery behavior.
- Address-change reconciliation where safely testable.
