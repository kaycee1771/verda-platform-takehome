# Primary References

References were re-checked on 2026-08-16. Material implementation decisions use the exact provider schema and version-specific documentation where available. Component versions not used in Phase 0 remain deliberately unselected in `versions.lock.yaml`.

- [Verda Terraform overview](https://docs.verda.com/infrastructure-as-code/terraform/)
- [Verda Terraform getting started](https://docs.verda.com/infrastructure-as-code/terraform/getting-started/)
- [Verda Terraform authentication](https://docs.verda.com/infrastructure-as-code/terraform/authentication/)
- [Verda compute instances](https://docs.verda.com/infrastructure-as-code/terraform/compute-instances/)
- [Verda CLI getting started](https://docs.verda.com/cli/getting-started/)
- [Verda CLI installation and capability overview](https://docs.verda.com/cli/)
- [Verda CLI instances, capacity, images, and locations](https://docs.verda.com/cli/instances/)
- [Verda CLI storage](https://docs.verda.com/cli/storage/)
- [Verda CLI cost and status](https://docs.verda.com/cli/cost-and-status/)
- [Verda object storage](https://docs.verda.com/cli/object-storage/)
- [Verda storage CLI](https://docs.verda.com/cli/storage/)
- [Verda pricing and billing](https://docs.verda.com/welcome-to-verda/pricing-and-billing/)
- [Verda instance security](https://docs.verda.com/cpu-and-gpu-instances/securing-your-instance/)
- [Terraform Registry: Verda provider 1.1.2](https://registry.terraform.io/providers/verda-cloud/verda/1.1.2)
- [Verda provider source repository](https://github.com/verda-cloud/terraform-provider-verda)
- [RKE2 high availability](https://docs.rke2.io/install/ha)
- [RKE2 network/CNI options](https://docs.rke2.io/networking/basic_network_options)
- [RKE2 networking services and ingress guidance](https://docs.rke2.io/networking/networking_services)
- [RKE2 CIS hardening guide](https://docs.rke2.io/security/hardening_guide)
- [Rancher current versions](https://ranchermanager.docs.rancher.com/versions)
- [Rancher architecture recommendations](https://ranchermanager.docs.rancher.com/v2.14/reference-guides/rancher-manager-architecture/architecture-recommendations)
- [Argo CD ApplicationSet generators](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators/)
- [Argo CD CI automation](https://argo-cd.readthedocs.io/en/stable/user-guide/ci_automation/)
- [Harbor vulnerability scanning](https://goharbor.io/docs/main/administration/vulnerability-scanning/)
- [Kubernetes PodSecurityPolicy removal](https://kubernetes.io/docs/concepts/security/pod-security-policy/)
- [Grafana Loki deployment modes](https://grafana.com/docs/loki/latest/setup/install/helm/)

## Recorded discrepancies

- The provider source README still contains pre-registry installation language, while Terraform Registry and current Verda documentation publish the provider. The registry and successful locked initialization govern.
- The generic Verda Terraform instance page mentions example attributes absent from provider 1.1.2. The exported 1.1.2 schema governs.
- Rancher v2.14.3 is listed as current, but no RKE2/Kubernetes pair is pinned in Phase 0 without a complete compatibility review. That review belongs before the versions are used.
