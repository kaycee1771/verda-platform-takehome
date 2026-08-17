# ADR 0013: Establish the Host Security Boundary Before RKE2

- **Status:** Accepted
- **Date:** 2026-08-17
- **Owners:** Platform, network, and security architecture
- **Blocking gates:** Phase 3 exit gate before any RKE2 installation

## Context

The current Verda project exposes one provider-managed public address per instance but no
self-service private network, security group, managed firewall, load balancer, floating address, or
DNS resource. RKE2, embedded etcd, Cilium, and Longhorn must therefore not be installed until the
hosts have a repeatable administrative boundary, encrypted internode path, stable storage identity,
and reboot-tested operating-system baseline.

Live discovery found Ubuntu 24.04 Minimal with a 1500-byte public-interface MTU, cgroup v2, a shared
root mount, the required storage kernel support, and one protected 100 GiB volume per node. The
administrative source is a single current operator address, not a durable office or VPN range.

## Decision

- Create the named `platform-admin` principal with key-only sudo access. Prove a fresh strict-host-key
  session before disabling direct root and password authentication.
- Keep SSH restricted to the approved administrative IPv4 `/32`, rate-limit new connections, and
  permit host WireGuard UDP only between the two exact peer endpoints for each node.
- Use one node-local WireGuard key pair per host. Never retrieve private keys; distribute only public
  keys within the ephemeral Ansible run.
- Use `10.250.0.0/24` for the management overlay, a WireGuard MTU of 1420, and reserve 1370 for the
  later Cilium VXLAN layer. The values follow the measured 1500-byte underlay, 80-byte WireGuard
  allowance, and 50-byte VXLAN allowance, and must remain explicit inputs rather than autodetected
  guesses.
- Own only the dedicated `inet verda_platform` nftables table. Use default-drop input and forwarding,
  accept established traffic, and keep output accepted. Phase 3 leaves HTTP, HTTPS, the Kubernetes
  API, RKE2 supervisor, etcd, kubelet, Cilium, metrics, and NodePort exposure closed on public
  interfaces.
- Identify each data disk through its provider-stable attachment identity, require the exact 100 GiB
  empty-device contract before first format, mount ext4 at `/var/lib/longhorn` by UUID, and fail
  closed on any unexpected signature, partition, size, or attachment.
- Apply firewall and SSH transitions with five-minute automatic recovery plus a verified fresh
  administrator session. Retain console recovery as the out-of-band fallback.
- Install host prerequisites and security updates, but disable automatic reboot. Reboots are serial,
  explicitly controlled, and proven by a changed kernel boot identity.

## Alternatives considered

- **Public RKE2 and etcd ports:** rejected because a host WireGuard boundary is available and the
  services do not exist in Phase 3.
- **Trust-on-first-use SSH:** rejected because Phase 2 host fingerprints already provide a pinning
  boundary.
- **A shared or controller-generated WireGuard private key:** rejected because compromise would span
  every peer and secret material would leave the node.
- **Assumed `/dev/vdX` disk ordering:** rejected because enumeration is not a persistent identity.
- **Whole-ruleset nftables replacement:** rejected because it would claim ownership of future RKE2
  and Cilium rules and make rollback unnecessarily broad.
- **Automatic unattended reboot:** rejected for the review window because uncoordinated quorum loss is
  a larger operational risk than a documented, serial maintenance action.

## Consequences

- Internode host traffic is encrypted and public attack surface is reduced before Kubernetes exists.
- The current administrative `/32` must be updated through the same rollback-protected workflow when
  the operator source changes; it is not a portable evaluator access solution.
- The 1370-byte Cilium value is a Phase 4 input reservation, not evidence that Cilium or RKE2 has been
  installed.
- Provider endpoint replacement requires a reviewed inventory, host-key, peer allowlist, and
  WireGuard reconciliation.
- The dedicated nftables table can coexist with future RKE2/Cilium-managed packet-processing rules,
  but the Phase 4 firewall matrix must be explicitly extended before services start.

## Validation evidence

`evidence/phase-3/` records a zero-drift cloud preflight, strict administrative-access proof, two
zero-change complete convergence passes, all six directed no-fragment overlay paths, sustained ring
traffic, public-port denials, UUID mount checks, three serial reboot identity changes, post-reboot
zero convergence, and final confirmation that RKE2 remains absent. Raw addresses, UUIDs, private
keys, resource IDs, credentials, and Ansible logs remain outside Git.

## Production evolution

Move administration behind an organization VPN or bastion with durable identity-aware policy. Use
Verda-managed private networking, firewalling, and a health-checked endpoint when those capabilities
are available. Centralize host audit output, rotate WireGuard and SSH identities, and manage
maintenance through a quorum-aware, tested patch policy.
