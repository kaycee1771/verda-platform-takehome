# Primary References

References were re-checked on 2026-08-16. Material implementation decisions use the exact provider
schema and version-specific documentation where available. Phase 1 quality tools and schema sources
are exact-pinned in `versions.lock.yaml`, `aqua.yaml`, and `schemas/schema-sources.lock.yaml`.

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
- [Verda current public pricing](https://verda.com/pricing)
- [Verda block-storage pricing](https://verda.com/block-storage)
- [Verda Public API](https://api.verda.com/v1/docs)
- [Verda release notes](https://docs.verda.com/welcome-to-verda/release-notes)
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
- [Rancher 2.14.3 support matrix](https://www.suse.com/suse-rancher/support-matrix/all-supported-versions/rancher-v2-14-3/)
- [Terraform CLI releases](https://releases.hashicorp.com/terraform/)
- [Aqua registry configuration](https://aquaproj.github.io/docs/reference/config/registry-config/)
- [Aqua checksum policy](https://aquaproj.github.io/docs/reference/config/checksum/)
- [Pre-commit configuration](https://pre-commit.com/)
- [Trivy misconfiguration scanning](https://trivy.dev/latest/docs/scanner/misconfiguration/)
- [Gitleaks command-line usage](https://github.com/gitleaks/gitleaks#usage)
- [Kubeconform schema locations](https://github.com/yannh/kubeconform#overriding-schemas-location)
- [Kyverno CLI policy tests](https://kyverno.io/docs/kyverno-cli/usage/test/)
- [Prometheus rule unit testing](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
- [GitHub Actions secure use](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)
- [GitHub workflow permissions](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions#permissions)
- [Docker build provenance option](https://docs.docker.com/reference/cli/docker/buildx/build/#provenance)
- [Argo CD v3.5.1 Application CRD](https://github.com/argoproj/argo-cd/blob/v3.5.1/manifests/crds/application-crd.yaml)
- [Kueue v0.19.1 Workload CRD](https://github.com/kubernetes-sigs/kueue/blob/v0.19.1/config/components/crd/bases/kueue.x-k8s.io_workloads.yaml)
- [Longhorn v1.12.1 generated CRDs](https://github.com/longhorn/longhorn-manager/blob/v1.12.1/k8s/crds.yaml)
- [Velero v1.18.1 Backup CRD](https://github.com/velero-io/velero/blob/v1.18.1/config/crd/v1/bases/velero.io_backups.yaml)

## Recorded discrepancies

- The provider source README still contains pre-registry installation language, while Terraform Registry and current Verda documentation publish the provider. The registry and successful locked initialization govern.
- The generic Verda Terraform instance page mentions example attributes absent from provider 1.1.2. The exported 1.1.2 schema governs.
- Current object-storage documentation describes a project Credentials section for Object Storage Access Keys, but that section is absent from the inspected project. Entitlement is a Phase 5 gate, not an assumed feature.
- Aqua's standard registry accepts the versioned release ref, not the raw registry commit. Bootstrap
  resolves `v4.552.0` and fails unless it still maps to the locked commit; package checksums remain
  mandatory.
