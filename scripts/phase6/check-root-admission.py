#!/usr/bin/env python3
"""Fail-closed admission boundary for the inert Phase 6 root candidate.

The checker reads only tracked, non-secret desired-state files. It never calls
the cluster, cloud, network, or Git. Live facts must first be reduced to the
boolean, sanitized ledger in ``config/phase6-root-admission.yaml``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT_BYTES = 2 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
CIPHERTEXT = re.compile(r"^Ag[A-Za-z0-9+/=]{78,}$")

REQUIRED_GATES = {
    "capacity": {
        "offline_capacity_admission_passed",
        "one_node_loss_headroom_proven",
        "renders_checksum_bound",
    },
    "component_activation": {
        "sealed_secrets_runtime_ready",
        "kyverno_audit_runtime_ready",
        "rancher_activation_ready",
        "harbor_activation_ready",
        "monitoring_runtime_ready",
        "loki_activation_ready",
        "alloy_activation_ready",
        "velero_activation_ready",
        "environment_foundations_ready",
    },
    "sealed_runtime": {
        "harbor_ciphertexts_locked",
        "environment_registry_ciphertexts_locked",
        "runtime_secrets_reconciled",
        "sealed_secrets_recovery_key_backed_up",
    },
    "tls": {
        "rancher_staging_certificate_verified",
        "rancher_production_certificate_ready",
        "harbor_staging_certificate_verified",
        "harbor_production_certificate_ready",
        "stage_a_certificates_ready",
    },
    "storage_s3": {
        "longhorn_runtime_healthy",
        "loki_s3_boundary_proven",
        "velero_s3_boundary_proven",
        "velero_backup_storage_location_available",
        "velero_kopia_repository_initialized",
    },
    "network_monitor": {
        "environment_default_denies_ready",
        "environment_dns_allowances_ready",
        "alloy_api_egress_proven",
        "monitoring_service_monitors_ready",
        "argocd_target_monitor_ready",
        "harbor_target_monitor_ready",
        "longhorn_target_monitor_ready",
        "rancher_target_monitor_ready",
        "traefik_target_monitor_ready",
        "prometheus_targets_ready",
        "grafana_datasources_ready",
    },
    "stage_a": {
        "image_digest_locked",
        "harbor_scan_completed_noncritical",
        "pull_secrets_reconciled",
        "workload_replicas_ready_1_1_2",
        "metrics_query_ready",
        "demo_dev_log_marker_ready",
    },
    "root": {
        "candidate_reviewed",
        "explicit_activation_authorized",
        "inclusion_allowed",
    },
}

REQUIRED_CAPACITY_COMPONENTS = {
    "rancher",
    "harbor",
    "kube_prometheus_stack",
    "loki",
    "alloy",
    "sealed_secrets",
    "kyverno",
    "velero",
    "environment_foundations",
    "platform_demo",
}

EXPECTED_CANDIDATE = {
    "prerequisites.yaml",
    "sealed-secrets.yaml",
    "kyverno-controller.yaml",
    "rancher.yaml",
    "harbor-secrets.yaml",
    "harbor-postgresql.yaml",
    "harbor-service.yaml",
    "monitoring-controller.yaml",
    "monitoring-resources.yaml",
    "loki.yaml",
    "alloy.yaml",
    "velero-controller.yaml",
    "velero-resources.yaml",
    "sealed-secrets-monitoring.yaml",
    "kyverno-monitoring.yaml",
    "kyverno-policies.yaml",
    "argocd-monitoring.yaml",
    "harbor-monitoring.yaml",
    "longhorn-monitoring.yaml",
    "rancher-monitoring.yaml",
    "traefik-monitoring.yaml",
    "environment-dev.yaml",
    "environment-staging.yaml",
    "environment-prod.yaml",
    "stage-a-smoke-dev.yaml",
    "stage-a-smoke-staging.yaml",
    "stage-a-smoke-prod.yaml",
}


class AdmissionError(ValueError):
    """A deterministic, non-sensitive admission error."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise AdmissionError("YAML contains a duplicate mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_yaml(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        if path.is_symlink() or not path.is_file():
            raise AdmissionError(f"required file is absent or unsafe: {relative}")
        size = path.stat().st_size
        if size <= 0 or size > MAX_INPUT_BYTES:
            raise AdmissionError(f"required file has an unsafe size: {relative}")
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AdmissionError(f"required file cannot be parsed: {relative}") from exc
    if not isinstance(value, dict):
        raise AdmissionError(f"required file is not a mapping: {relative}")
    return value


def mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AdmissionError(f"{label} must be a mapping")
    return value


def require_true(mapping_value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(mapping_value) != keys:
        raise AdmissionError(f"{label} has a missing or unexpected gate")
    for key in sorted(keys):
        if mapping_value[key] is not True:
            raise AdmissionError(f"{label}.{key} is not satisfied")


def normalize_resource(value: Any) -> str:
    if not isinstance(value, str):
        raise AdmissionError("root resource entries must be strings")
    normalized = value.replace("\\", "/").removeprefix("./").rstrip("/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise AdmissionError("root resource entry is unsafe")
    return normalized


def root_state(root: Path) -> bool:
    root_doc = load_yaml(root, "gitops/root/kustomization.yaml")
    resources = root_doc.get("resources")
    if not isinstance(resources, list):
        raise AdmissionError("root resources must be a list")
    normalized = [normalize_resource(item) for item in resources]
    phase6_entries = [item for item in normalized if item == "phase6" or item.startswith("phase6/")]
    if len(phase6_entries) > 1:
        raise AdmissionError("root contains ambiguous Phase 6 entries")
    included = phase6_entries == ["phase6"]

    candidate = load_yaml(root, "gitops/root/phase6/kustomization.yaml")
    candidate_resources = candidate.get("resources")
    if not isinstance(candidate_resources, list):
        raise AdmissionError("Phase 6 candidate resources must be a list")
    normalized_candidate = [normalize_resource(item) for item in candidate_resources]
    if len(normalized_candidate) != len(set(normalized_candidate)):
        raise AdmissionError("Phase 6 candidate contains duplicate resources")
    if set(normalized_candidate) != EXPECTED_CANDIDATE:
        raise AdmissionError("Phase 6 candidate inventory is incomplete or unexpected")

    application_names: set[str] = set()
    for resource in sorted(EXPECTED_CANDIDATE):
        application = load_yaml(root, f"gitops/root/phase6/{resource}")
        if application.get("apiVersion") != "argoproj.io/v1alpha1" or application.get("kind") != "Application":
            raise AdmissionError(f"Phase 6 candidate resource is not an Argo CD Application: {resource}")
        metadata = mapping(application.get("metadata"), f"Phase 6 candidate metadata: {resource}")
        name = metadata.get("name")
        if not isinstance(name, str) or not name or metadata.get("namespace") != "argocd":
            raise AdmissionError(f"Phase 6 candidate identity is invalid: {resource}")
        if name in application_names:
            raise AdmissionError("Phase 6 candidate contains duplicate Application names")
        application_names.add(name)
        specification = mapping(application.get("spec"), f"Phase 6 candidate spec: {resource}")
        destination = mapping(specification.get("destination"), f"Phase 6 candidate destination: {resource}")
        if destination.get("server") != "https://kubernetes.default.svc" or not isinstance(destination.get("namespace"), str):
            raise AdmissionError(f"Phase 6 candidate destination is invalid: {resource}")
    return included


def check_ledger(root: Path) -> None:
    ledger = load_yaml(root, "config/phase6-root-admission.yaml")
    if ledger.get("schema_version") != 1:
        raise AdmissionError("root admission schema_version must equal 1")
    if ledger.get("admission_status") != "admitted":
        raise AdmissionError("root admission_status must equal admitted")
    gates = mapping(ledger.get("gates"), "root admission gates")
    if set(gates) != set(REQUIRED_GATES):
        raise AdmissionError("root admission ledger has a missing or unexpected gate group")
    for group in sorted(REQUIRED_GATES):
        require_true(mapping(gates[group], f"root admission gates.{group}"), REQUIRED_GATES[group], f"root admission gates.{group}")


def positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def check_capacity_contract_shape(root: Path) -> None:
    contract = load_yaml(root, "config/phase6-capacity-admission.yaml")
    if contract.get("schema_version") != 1 or contract.get("admission_status") != "ready":
        raise AdmissionError("capacity admission contract is not ready")
    baseline = mapping(contract.get("baseline"), "capacity baseline")
    required_positive = {
        "node_count",
        "allocatable_cpu_millicores",
        "allocatable_memory_bytes",
        "one_node_loss_allocatable_cpu_millicores",
        "one_node_loss_allocatable_memory_bytes",
        "existing_requested_cpu_millicores",
        "existing_requested_memory_bytes",
        "required_cpu_reserve_millicores",
        "required_memory_reserve_bytes",
        "storage_available_bytes",
        "worst_two_node_storage_available_bytes",
        "required_storage_reserve_bytes",
    }
    for key in sorted(required_positive):
        if not positive_int(baseline.get(key)):
            raise AdmissionError(f"capacity baseline.{key} is incomplete")
    if baseline.get("node_count") != 3:
        raise AdmissionError("capacity baseline node_count must equal 3")

    components = mapping(contract.get("components"), "capacity components")
    if set(components) != REQUIRED_CAPACITY_COMPONENTS:
        raise AdmissionError("capacity component inventory is incomplete or unexpected")
    for name in sorted(REQUIRED_CAPACITY_COMPONENTS):
        component = mapping(components[name], f"capacity component {name}")
        if not SHA256.fullmatch(str(component.get("render_sha256", ""))):
            raise AdmissionError(f"capacity component {name} is not checksum-bound")
        if not positive_int(component.get("expected_document_count")):
            raise AdmissionError(f"capacity component {name}.expected_document_count is incomplete")
        for field in ("expected_workload_count", "expected_pvc_definition_count"):
            count = component.get(field)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise AdmissionError(f"capacity component {name}.{field} is incomplete")


def run_capacity_preflight(root: Path) -> None:
    """Regenerate exact renders, verify bindings, then run real admission.

    This is deliberately not projection-only. A green ledger cannot substitute
    for the protected candidate-node evidence or scheduler/storage arithmetic.
    """

    commands = (
        [
            sys.executable,
            str(root / "scripts/phase6/render-capacity-inputs.py"),
            "--verify-contract",
            str(root / "config/phase6-capacity-admission.yaml"),
        ],
        [
            sys.executable,
            str(root / "scripts/phase6/capacity-admission.py"),
            "--contract",
            str(root / "config/phase6-capacity-admission.yaml"),
        ],
    )
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            step = "render regeneration" if index == 0 else "non-projection admission"
            raise AdmissionError(f"capacity {step} did not pass")


def all_boolean_gates_ready(document: dict[str, Any], label: str) -> None:
    gates = mapping(document.get("blocking_gates"), f"{label} blocking_gates")
    if not gates or any(value is not True for value in gates.values()):
        raise AdmissionError(f"{label} blocking gates are not all satisfied")


def check_component_contracts(root: Path) -> None:
    rancher = load_yaml(root, "platform/management/rancher/values.yaml")
    require_true(mapping(rancher.get("gates"), "Rancher gates"), {"stagingCertificateVerified", "imageDigestsLocked"}, "Rancher gates")
    if mapping(rancher.get("rancher"), "Rancher values").get("enabled") is not True:
        raise AdmissionError("Rancher activation is disabled")

    harbor_secrets = load_yaml(root, "platform/management/harbor/secrets/values.yaml")
    if harbor_secrets.get("enabled") is not True:
        raise AdmissionError("Harbor SealedSecrets activation is disabled")
    require_true(mapping(harbor_secrets.get("gates"), "Harbor SealedSecrets gates"), {"ciphertextsLocked"}, "Harbor SealedSecrets gates")
    ciphertexts = mapping(harbor_secrets.get("ciphertexts"), "Harbor ciphertexts")
    if not ciphertexts or any(not CIPHERTEXT.fullmatch(value) for value in ciphertexts.values() if isinstance(value, str)) or any(not isinstance(value, str) for value in ciphertexts.values()):
        raise AdmissionError("Harbor ciphertexts contain an unresolved sentinel")

    postgres = load_yaml(root, "platform/management/harbor/postgresql/values.yaml")
    if postgres.get("enabled") is not True:
        raise AdmissionError("Harbor PostgreSQL activation is disabled")
    require_true(mapping(postgres.get("gates"), "Harbor PostgreSQL gates"), {"sealedCredentialsReady", "imageDigestLocked"}, "Harbor PostgreSQL gates")

    harbor = load_yaml(root, "platform/management/harbor/service/values.yaml")
    require_true(mapping(harbor.get("gates"), "Harbor gates"), {"stagingCertificateVerified", "sealedSecretsReady", "postgresqlReady", "capacityAdmitted", "imageDigestsLocked"}, "Harbor gates")
    if mapping(harbor.get("harbor"), "Harbor values").get("enabled") is not True:
        raise AdmissionError("Harbor activation is disabled")

    for relative, label in (
        ("platform/management/loki/activation-contract.yaml", "Loki"),
        ("observability/alloy/image-lock.yaml", "Alloy"),
        ("platform/management/velero/activation-contract.yaml", "Velero"),
    ):
        contract = load_yaml(root, relative)
        if contract.get("activation_status") != "ready":
            raise AdmissionError(f"{label} activation contract is not ready")
        all_boolean_gates_ready(contract, label)
        if label in {"Loki", "Velero"} and mapping(contract.get("object_storage"), f"{label} object storage").get("status") != "live-proven":
            raise AdmissionError(f"{label} object storage is not live-proven")

    monitoring = load_yaml(root, "platform/management/monitoring/image-lock.yaml")
    if monitoring.get("selection_status") != "verified":
        raise AdmissionError("monitoring image lock is not verified")
    images = monitoring.get("images")
    if not isinstance(images, list) or not images:
        raise AdmissionError("monitoring image inventory is empty")
    for item in images:
        if not isinstance(item, dict) or not IMAGE_DIGEST.fullmatch(str(item.get("digest", ""))):
            raise AdmissionError("monitoring image inventory contains an invalid digest")

    for relative, label in (
        ("platform/management/sealed-secrets/values.yaml", "Sealed Secrets"),
        ("platform/management/kyverno/values.yaml", "Kyverno"),
    ):
        values = load_yaml(root, relative)
        tags: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "tag" and isinstance(child, str):
                        tags.append(child)
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(values)
        if not tags or any("@sha256:" not in tag or not IMAGE_DIGEST.fullmatch("sha256:" + tag.rsplit("@sha256:", 1)[1]) for tag in tags):
            raise AdmissionError(f"{label} contains an image without an immutable digest")


def check_sealed_environment_credentials(root: Path) -> None:
    for environment in ("dev", "staging", "prod"):
        document = load_yaml(root, f"environments/{environment}/namespace/registry-credentials.yaml")
        encrypted = mapping(mapping(document.get("spec"), f"{environment} SealedSecret spec").get("encryptedData"), f"{environment} SealedSecret encryptedData")
        ciphertext = encrypted.get(".dockerconfigjson")
        if not isinstance(ciphertext, str) or not CIPHERTEXT.fullmatch(ciphertext):
            raise AdmissionError(f"{environment} registry ciphertext contains an unresolved sentinel")


def check_stage_a(root: Path) -> None:
    expected_replicas = {"dev": 1, "staging": 1, "prod": 2}
    digests: set[str] = set()
    for environment, replicas in expected_replicas.items():
        values = load_yaml(root, f"applications/stage-a-smoke/values-{environment}.yaml")
        if values.get("environment") != environment or values.get("replicas") != replicas:
            raise AdmissionError(f"Stage A {environment} identity or replica contract is invalid")
        activation = mapping(values.get("activation"), f"Stage A {environment} activation")
        require_true(activation, {"enabled", "imageDigestLocked", "pullSecretReady", "serviceMonitorCRDReady"}, f"Stage A {environment} activation")
        certificate = mapping(values.get("certificate"), f"Stage A {environment} certificate")
        if certificate.get("bootstrapEnabled") is not True or certificate.get("stagingCertificateVerified") is not True:
            raise AdmissionError(f"Stage A {environment} certificate gates are not satisfied")
        digest = mapping(values.get("image"), f"Stage A {environment} image").get("digest")
        if not isinstance(digest, str) or not IMAGE_DIGEST.fullmatch(digest):
            raise AdmissionError(f"Stage A {environment} image digest contains an unresolved sentinel")
        digests.add(digest)
    if len(digests) != 1:
        raise AdmissionError("Stage A environments do not select one promoted image digest")


def evaluate(root: Path, capacity_preflight: Any = run_capacity_preflight) -> tuple[bool, str | None]:
    try:
        included = root_state(root)
    except AdmissionError as exc:
        return False, str(exc)
    try:
        check_ledger(root)
        check_capacity_contract_shape(root)
        check_component_contracts(root)
        check_sealed_environment_credentials(root)
        check_stage_a(root)
        capacity_preflight(root)
    except AdmissionError as exc:
        if included:
            return False, "Phase 6 candidate is included before every admission gate is satisfied"
        return False, str(exc)
    if not included:
        return False, "Phase 6 admission is complete but root inclusion is absent"
    return True, None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the Phase 6 root-admission boundary")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (tests only; defaults to this checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    passed, reason = evaluate(root)
    if not passed:
        print(f"[FAIL] Phase 6 root admission: {reason}", file=sys.stderr)
        return 1
    print(json.dumps({"admission": "passed", "phase": 6, "root_included": True}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
