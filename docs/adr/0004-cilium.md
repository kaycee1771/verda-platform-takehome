# ADR 0004: Use RKE2-Bundled Cilium and Hubble

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Network architecture
- **Blocking gates:** Exact bundled chart follows the selected RKE2 patch

## Context

The platform needs Kubernetes NetworkPolicy enforcement and credible flow evidence. RKE2 supports multiple bundled CNIs; Cilium provides both enforcement and Hubble observability.

## Decision

Select `cni: cilium` before first RKE2 start and enable Hubble through the RKE2-matched HelmChartConfig. Start with the RKE2-supported conservative dataplane: keep kube-proxy, avoid BGP, and avoid advanced routing unless a proven requirement emerges.

## Alternatives considered

- **Canal:** supported and simpler but provides a weaker integrated flow-visibility story.
- **Calico:** capable and supported; Cilium/Hubble better aligns policy proof with observability.
- **Flannel:** rejected because it does not enforce NetworkPolicy.

## Consequences

- Kernel and MTU prerequisites must be verified before installation.
- CNI and cluster/service CIDRs are immutable design-time selections; changing them implies rebuild.
- Portable Kubernetes NetworkPolicy remains the default policy language.

## Validation evidence

Current RKE2 network documentation reviewed 2026-08-16 lists Cilium as supported and documents Hubble enablement. Acceptance requires Cilium health, connectivity tests, DNS/service tests, and Hubble evidence for allowed and denied flows.

## Production evolution

Evaluate native routing, BGP, egress control, encryption, and kube-proxy replacement only against verified network topology, performance needs, and failure tests.
