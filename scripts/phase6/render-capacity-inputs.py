#!/usr/bin/env python3
"""Render the ten Phase 6 capacity inputs without contacting a cluster.

The output is capacity evidence, not Kubernetes desired state.  It expands the
checked-in values against checksum-pinned chart archives, substitutes only the
minimum non-secret activation sentinels needed to expose latent workloads, and
adds explicit projections for operator/generated workloads that Helm cannot
render.  Every output is canonical YAML and is written below ignored `.local/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "versions.lock.yaml"
DEFAULT_CACHE = ROOT / ".local" / "chart-cache"
DEFAULT_OUTPUT = ROOT / ".local" / "phase6" / "renders"
SYNTHETIC_DIGEST = "sha256:" + "c" * 64
MAXIMUM_RENDER_BYTES = 16 * 1024 * 1024

CHARTS = {
    "rancher": ("rancher", "rancher"),
    "harbor": ("harbor", "harbor"),
    "kube_prometheus_stack": ("kube-prometheus-stack", "kube-prometheus-stack"),
    "loki": ("loki", "loki"),
    "alloy": ("alloy", "alloy"),
    "sealed_secrets": ("sealed-secrets", "sealed-secrets"),
    "kyverno": ("kyverno", "kyverno"),
    "velero": ("velero", "velero"),
}


class RenderError(ValueError):
    """Raised when a projection cannot be reproduced safely."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate YAML mapping keys."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise RenderError("YAML contains a duplicate mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
UniqueKeyLoader.add_constructor(
    "tag:yaml.org,2002:value",
    lambda loader, node: loader.construct_scalar(node),
)


def load_one(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RenderError(f"required source is not a regular file: {path}")
    documents = [item for item in yaml.load_all(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) if item is not None]
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise RenderError(f"required source must contain one mapping: {path}")
    return documents[0]


def load_many(payload: str, label: str) -> list[dict[str, Any]]:
    try:
        documents = [item for item in yaml.load_all(payload, Loader=UniqueKeyLoader) if item is not None]
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", "invalid YAML")
        raise RenderError(f"{label} did not produce valid duplicate-free YAML{location}: {problem}") from exc
    if not documents or any(not isinstance(item, dict) for item in documents):
        raise RenderError(f"{label} did not produce Kubernetes mappings")
    return documents


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_source(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise RenderError(f"capacity source escapes the repository: {path}") from exc
    return {"path": relative, "recursive": False, "sha256": sha256(resolved)}


def tracked_tree(path: Path) -> list[dict[str, Any]]:
    resolved = path.resolve()
    files = [item for item in sorted(resolved.rglob("*")) if item.is_file()]
    if not files or any(item.is_symlink() for item in files):
        raise RenderError(f"recursive capacity source must contain regular files only: {path}")
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.relative_to(resolved).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
        digest.update(b"\0")
    return [{"path": resolved.relative_to(ROOT.resolve()).as_posix(), "recursive": True, "sha256": digest.hexdigest()}]


def chart_path(lock: dict[str, Any], cache: Path, lock_name: str, archive_name: str) -> Path:
    item = lock.get("helm_charts", {}).get(lock_name)
    if not isinstance(item, dict):
        raise RenderError(f"missing chart lock: {lock_name}")
    version = item.get("version")
    expected = item.get("archive_sha256")
    path = cache / f"{archive_name}-{version}.tgz"
    if not path.is_file() or path.is_symlink():
        raise RenderError(f"pinned chart archive is absent: {path}")
    if sha256(path) != expected:
        raise RenderError(f"pinned chart archive checksum mismatch: {lock_name}")
    return path


def run(command: list[str], label: str) -> str:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        suffix = detail[-1] if detail else "no diagnostic"
        raise RenderError(f"{label} failed: {suffix}")
    return result.stdout


def helm_render(
    helm: str,
    release: str,
    namespace: str,
    chart: Path,
    values: dict[str, Any] | Path,
    temporary: Path,
) -> list[dict[str, Any]]:
    if isinstance(values, Path):
        values_path = values
    else:
        values_path = temporary / f"{release}-capacity-values.yaml"
        values_path.write_text(yaml.safe_dump(values, sort_keys=True), encoding="utf-8")
    output = run(
        [
            helm,
            "template",
            release,
            str(chart),
            "--namespace",
            namespace,
            "--kube-version",
            "1.35.7",
            "--include-crds",
            "--values",
            str(values_path),
        ],
        f"Helm render {release}",
    )
    return load_many(output, f"Helm render {release}")


def kustomize_render(kubectl: str, path: Path) -> list[dict[str, Any]]:
    return load_many(run([kubectl, "kustomize", str(path)], f"Kustomize render {path}"), str(path))


def projection_annotations(document: dict[str, Any], source: str, mode: str = "normal") -> None:
    metadata = document.setdefault("metadata", {})
    annotations = metadata.setdefault("annotations", {})
    annotations["capacity.platform.verda.io/projection-only"] = "true"
    annotations["capacity.platform.verda.io/source"] = source
    if mode != "normal":
        annotations["capacity.platform.verda.io/mode"] = mode


def velero_generated_projections(source: dict[str, Any]) -> list[dict[str, Any]]:
    workloads = source["workloads"]
    result: list[dict[str, Any]] = []
    for name in ("data-mover", "repository-maintenance"):
        item = workloads[name]
        replicas = item["maximum_concurrent_pods"]
        document = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": f"capacity-model-velero-{name}", "namespace": "velero"},
            "spec": {
                "replicas": replicas,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"capacity.platform.verda.io/workload": name}},
                "template": {
                    "metadata": {"labels": {"capacity.platform.verda.io/workload": name}},
                    "spec": {
                        "containers": [
                            {
                                "name": name,
                                "image": f"projection.invalid/{name}@{SYNTHETIC_DIGEST}",
                                "resources": {
                                    "requests": {
                                        "cpu": item["requests_per_pod"]["cpu"],
                                        "memory": item["requests_per_pod"]["memory"],
                                    },
                                    "limits": {
                                        "cpu": item["limits_per_pod"]["cpu"],
                                        "memory": item["limits_per_pod"]["memory"],
                                    },
                                },
                            }
                        ]
                    },
                },
            },
        }
        projection_annotations(document, "velero-capacity-input-v1", "peak-only")
        result.append(document)
    return result


def canonical_write(path: Path, documents: Iterable[dict[str, Any]]) -> dict[str, int | str]:
    material = list(documents)
    if not material:
        raise RenderError(f"capacity render contains no objects: {path.name}")
    payload = yaml.safe_dump_all(material, explicit_start=True, sort_keys=True, width=4096).encode("utf-8")
    if len(payload) > MAXIMUM_RENDER_BYTES:
        raise RenderError(f"capacity render exceeds {MAXIMUM_RENDER_BYTES} bytes: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    workload_kinds = {"Deployment", "StatefulSet", "DaemonSet", "Job", "Pod"}
    workloads = sum(item.get("kind") in workload_kinds for item in material)
    pvcs = sum(item.get("kind") == "PersistentVolumeClaim" for item in material)
    pvcs += sum(
        len(item.get("spec", {}).get("volumeClaimTemplates", []))
        for item in material
        if item.get("kind") == "StatefulSet"
    )
    return {
        "render_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_document_count": len(material),
        "expected_workload_count": workloads,
        "expected_pvc_definition_count": pvcs,
    }


def component_entry(output: Path, result: dict[str, int | str], sources: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "render_path": f"../.local/phase6/renders/{output.name}",
        **result,
        "source_inputs": sorted(sources, key=lambda item: item["path"]),
    }
    entry.update(extra)
    return entry


def inject_rancher_hook_limit(
    documents: list[dict[str, Any]], limit_range: dict[str, Any]
) -> None:
    """Model the API-server LimitRange mutation for the exact Rancher hook."""

    limits = limit_range.get("spec", {}).get("limits")
    if not isinstance(limits, list) or len(limits) != 1:
        raise RenderError("cattle-system LimitRange must contain one Container rule")
    rule = limits[0]
    if not isinstance(rule, dict) or rule.get("type") != "Container":
        raise RenderError("cattle-system LimitRange must contain one Container rule")
    request = rule.get("defaultRequest")
    resource_limit = rule.get("default")
    if request != {"cpu": "100m", "memory": "128Mi"} or resource_limit != {
        "cpu": "500m",
        "memory": "256Mi",
    }:
        raise RenderError("cattle-system LimitRange resources changed")

    matches = []
    for document in documents:
        metadata = document.get("metadata", {})
        annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
        if (
            document.get("apiVersion") == "batch/v1"
            and document.get("kind") == "Job"
            and isinstance(metadata, dict)
            and metadata.get("name") == "rancher-pre-upgrade"
            and isinstance(annotations, dict)
            and annotations.get("helm.sh/hook") == "pre-upgrade"
        ):
            matches.append(document)
    if len(matches) != 1:
        raise RenderError("Rancher render must contain exactly one pre-upgrade hook Job")
    containers = matches[0].get("spec", {}).get("template", {}).get("spec", {}).get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise RenderError("Rancher pre-upgrade hook must contain exactly one container")
    container = containers[0]
    if not isinstance(container, dict) or container.get("name") != "rancher-pre-upgrade":
        raise RenderError("Rancher pre-upgrade hook container identity changed")
    if "resources" in container:
        raise RenderError("Rancher hook gained chart-owned resources; remove the projection")
    container["resources"] = {
        "requests": deepcopy(request),
        "limits": deepcopy(resource_limit),
    }
    projection_annotations(matches[0], "cattle-system-limit-range-admission")


def render_all(args: argparse.Namespace) -> dict[str, Any]:
    lock = load_one(LOCK)
    output_dir = args.output_dir.resolve()
    cache = args.chart_cache.resolve()
    components: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="phase6-capacity-") as directory:
        temporary = Path(directory)

        rancher_source = ROOT / "platform/management/rancher/values.yaml"
        rancher_values = deepcopy(load_one(rancher_source)["rancher"])
        rancher_values.pop("enabled", None)
        rancher_docs = helm_render(args.helm, "rancher", "cattle-system", chart_path(lock, cache, "rancher", "rancher"), rancher_values, temporary)
        rancher_limit_source = ROOT / "platform/management/namespaces/cattle-system-limit-range.yaml"
        rancher_limit = load_one(rancher_limit_source)
        inject_rancher_hook_limit(rancher_docs, rancher_limit)
        rancher_out = output_dir / "rancher.yaml"
        components["rancher"] = component_entry(rancher_out, canonical_write(rancher_out, rancher_docs), [tracked_source(LOCK), tracked_source(rancher_source), tracked_source(rancher_limit_source)], chart_archive_sha256=lock["helm_charts"]["rancher"]["archive_sha256"], projection_semantics="upstream chart with checked-in values and exact cattle-system LimitRange mutation for the pre-upgrade hook; activation gate not asserted")

        harbor_source = ROOT / "platform/management/harbor/service/values.yaml"
        harbor_values = deepcopy(load_one(harbor_source)["harbor"])
        harbor_values.pop("enabled", None)
        harbor_docs = helm_render(args.helm, "harbor", "harbor", chart_path(lock, cache, "harbor", "harbor"), harbor_values, temporary)
        postgres_chart = ROOT / "platform/management/harbor/postgresql"
        postgres_values = load_one(postgres_chart / "values.yaml")
        postgres_values["enabled"] = True
        postgres_values["gates"] = {"sealedCredentialsReady": True, "imageDigestLocked": True}
        harbor_docs.extend(helm_render(args.helm, "harbor-postgresql", "harbor", postgres_chart, postgres_values, temporary))
        harbor_out = output_dir / "harbor.yaml"
        components["harbor"] = component_entry(harbor_out, canonical_write(harbor_out, harbor_docs), [tracked_source(LOCK), tracked_source(harbor_source), *tracked_tree(postgres_chart)], chart_archive_sha256=lock["helm_charts"]["harbor"]["archive_sha256"], projection_semantics="Harbor upstream chart plus separately-owned PostgreSQL; non-secret gates enabled only in ignored projection")

        monitoring_source = ROOT / "platform/management/monitoring/values.yaml"
        monitoring_docs = helm_render(args.helm, "monitoring", "monitoring", chart_path(lock, cache, "kube_prometheus_stack", "kube-prometheus-stack"), monitoring_source, temporary)
        replaced = [item for item in monitoring_docs if item.get("apiVersion") == "monitoring.coreos.com/v1" and item.get("kind") in {"Prometheus", "Alertmanager"}]
        if {item.get("kind") for item in replaced} != {"Prometheus", "Alertmanager"} or len(replaced) != 2:
            raise RenderError("monitoring render must contain exactly one Prometheus and one Alertmanager projection source")
        monitoring_docs = [item for item in monitoring_docs if item not in replaced]
        operator_projection = ROOT / "platform/management/monitoring/capacity/operator-workloads.capacity-input"
        operator_docs = load_many(operator_projection.read_text(encoding="utf-8"), str(operator_projection))
        monitoring_docs.extend(operator_docs)
        monitoring_out = output_dir / "kube-prometheus-stack.yaml"
        components["kube_prometheus_stack"] = component_entry(monitoring_out, canonical_write(monitoring_out, monitoring_docs), [tracked_source(LOCK), tracked_source(monitoring_source), tracked_source(operator_projection)], chart_archive_sha256=lock["helm_charts"]["kube_prometheus_stack"]["archive_sha256"], projection_semantics="exact chart render with Prometheus and Alertmanager CRs replaced one-for-one by operator StatefulSet projections", operator_projection_replacement_count=2)

        for component, source, namespace in (
            ("loki", ROOT / "platform/management/loki/values.yaml", "logging"),
            ("alloy", ROOT / "observability/alloy/values.yaml", "logging"),
            ("sealed_secrets", ROOT / "platform/management/sealed-secrets/values.yaml", "sealed-secrets"),
            ("kyverno", ROOT / "platform/management/kyverno/values.yaml", "kyverno"),
            ("velero", ROOT / "platform/management/velero/values.yaml", "velero"),
        ):
            archive_name, release = CHARTS[component]
            docs = helm_render(args.helm, release, namespace, chart_path(lock, cache, component, archive_name), source, temporary)
            sources = [tracked_source(LOCK), tracked_source(source)]
            extra: dict[str, Any] = {
                "chart_archive_sha256": lock["helm_charts"][component]["archive_sha256"],
                "projection_semantics": "exact upstream chart render",
            }
            if component == "velero":
                peak_source = ROOT / "platform/management/velero/capacity-input.yaml"
                docs.extend(velero_generated_projections(load_one(peak_source)))
                sources.append(tracked_source(peak_source))
                extra["projection_semantics"] = "exact chart render plus bounded data-mover and repository-maintenance peak projections"
                extra["generated_peak_projection_count"] = 2
            out = output_dir / f"{component.replace('_', '-')}.yaml"
            components[component] = component_entry(out, canonical_write(out, docs), sources, **extra)

        environment_docs: list[dict[str, Any]] = []
        environment_sources: list[dict[str, Any]] = []
        for name in ("dev", "staging", "prod"):
            source = ROOT / f"environments/{name}/namespace"
            environment_docs.extend(kustomize_render(args.kubectl, source))
            environment_sources.extend(tracked_tree(source))
        environment_out = output_dir / "environment-foundations.yaml"
        components["environment_foundations"] = component_entry(environment_out, canonical_write(environment_out, environment_docs), environment_sources, projection_semantics="exact three-environment Kustomize renders")

        demo_chart = ROOT / "applications/stage-a-smoke/chart"
        demo_docs: list[dict[str, Any]] = []
        demo_sources = tracked_tree(demo_chart)
        for name in ("dev", "staging", "prod"):
            values_path = ROOT / f"applications/stage-a-smoke/values-{name}.yaml"
            values = load_one(values_path)
            values["activation"] = {"enabled": True, "imageDigestLocked": True, "pullSecretReady": True, "serviceMonitorCRDReady": True}
            values["certificate"]["bootstrapEnabled"] = True
            values["certificate"]["stagingCertificateVerified"] = True
            values["image"]["digest"] = SYNTHETIC_DIGEST
            rendered = helm_render(args.helm, f"stage-a-smoke-{name}", values["namespace"], demo_chart, values, temporary)
            for document in rendered:
                projection_annotations(document, f"stage-a-smoke-{name}-latent-workload")
            demo_docs.extend(rendered)
            demo_sources.append(tracked_source(values_path))
        demo_out = output_dir / "platform-demo.yaml"
        components["platform_demo"] = component_entry(demo_out, canonical_write(demo_out, demo_docs), demo_sources, projection_semantics="latent dev/staging/prod render with synthetic nonzero digest and gates enabled only in ignored projection", immutable_activation_input_remaining="real Harbor digest and live readiness gates")

    return components


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--helm", default=os.environ.get("PHASE6_HELM", shutil.which("helm") or "helm"))
    parser.add_argument("--kubectl", default=os.environ.get("PHASE6_KUBECTL", shutil.which("kubectl") or "kubectl"))
    parser.add_argument("--json", action="store_true", help="emit contract-ready component metadata")
    parser.add_argument("--metadata-output", type=Path, help="write contract-ready metadata below ignored local state")
    parser.add_argument("--verify-contract", type=Path, help="fail unless tracked component checksums and counts match")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        components = render_all(args)
    except (OSError, RenderError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] Phase 6 capacity render: {exc}", file=sys.stderr)
        return 1
    result = {"schema_version": 1, "component_count": len(components), "components": components}
    if args.verify_contract is not None:
        contract = load_one(args.verify_contract.resolve())
        expected_components = contract.get("components")
        if not isinstance(expected_components, dict) or set(expected_components) != set(components):
            print("[FAIL] Phase 6 capacity render: contract component inventory changed", file=sys.stderr)
            return 1
        exact_fields = {
            "render_path",
            "render_sha256",
            "expected_document_count",
            "expected_workload_count",
            "expected_pvc_definition_count",
            "chart_archive_sha256",
            "source_inputs",
            "operator_projection_replacement_count",
            "generated_peak_projection_count",
            "immutable_activation_input_remaining",
        }
        for name, actual in components.items():
            expected = expected_components[name]
            if any(expected.get(field) != actual.get(field) for field in exact_fields):
                print(f"[FAIL] Phase 6 capacity render: contract metadata changed for {name}", file=sys.stderr)
                return 1
    if args.metadata_output is not None:
        destination = args.metadata_output.resolve()
        try:
            destination.relative_to((ROOT / ".local").resolve())
        except ValueError:
            print("[FAIL] Phase 6 capacity render: metadata output must stay below .local", file=sys.stderr)
            return 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")) if args.json else "[PASS] Phase 6 capacity inputs rendered and checksum-bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
