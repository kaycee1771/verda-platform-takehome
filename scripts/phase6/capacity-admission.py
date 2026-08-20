#!/usr/bin/env python3
"""Deterministic, fail-closed Phase 6 scheduling and PVC admission gate.

The gate consumes only checksum-bound, offline Helm/Kustomize render outputs. It
does not invoke Helm, kubectl, a cloud API, or the live cluster. The tracked
contract intentionally remains blocked until every mandatory component render
and the exact sanitized baseline are supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "phase6-capacity-admission.yaml"
MAXIMUM_INPUT_BYTES = 16 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NUMBER = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|\.[0-9]+"
CPU_QUANTITY = re.compile(rf"^({NUMBER})([num]?)$")
BYTE_QUANTITY = re.compile(rf"^({NUMBER})([EPTGMK]i?|)$")
REQUIRED_COMPONENTS = frozenset(
    {
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
)
STANDARD_WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "Job", "Pod"})
CAPACITY_BEARING_UNSUPPORTED_KINDS = frozenset(
    {
        ("autoscaling", "HorizontalPodAutoscaler"),
        ("autoscaling.k8s.io", "VerticalPodAutoscaler"),
        ("monitoring.coreos.com", "Prometheus"),
        ("monitoring.coreos.com", "PrometheusAgent"),
        ("monitoring.coreos.com", "Alertmanager"),
        ("monitoring.coreos.com", "ThanosRuler"),
    }
)


class CapacityAdmissionError(ValueError):
    """Raised when an admission input is incomplete, ambiguous, or unsafe."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise CapacityAdmissionError("YAML contains a duplicate mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class PodResources:
    request_cpu_millicores: int
    request_memory_bytes: int
    limit_cpu_millicores: int
    limit_memory_bytes: int

    def scaled(self, replicas: int) -> "PodResources":
        return PodResources(
            self.request_cpu_millicores * replicas,
            self.request_memory_bytes * replicas,
            self.limit_cpu_millicores * replicas,
            self.limit_memory_bytes * replicas,
        )

    def plus(self, other: "PodResources") -> "PodResources":
        return PodResources(
            self.request_cpu_millicores + other.request_cpu_millicores,
            self.request_memory_bytes + other.request_memory_bytes,
            self.limit_cpu_millicores + other.limit_cpu_millicores,
            self.limit_memory_bytes + other.limit_memory_bytes,
        )


ZERO_RESOURCES = PodResources(0, 0, 0, 0)


@dataclass(frozen=True)
class ComponentCapacity:
    document_count: int
    workload_count: int
    pvc_definition_count: int
    steady: PodResources
    peak: PodResources
    logical_pvc_bytes: int
    raw_pvc_bytes: int
    one_node_loss_pvc_bytes: int


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapacityAdmissionError(f"{label} must be a mapping")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapacityAdmissionError(f"{label} must be a list")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CapacityAdmissionError(f"{label} must be an integer >= {minimum}")
    return value


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CapacityAdmissionError(f"{label} must be a regular, non-symlink file")
    size = path.stat().st_size
    if size == 0 or size > MAXIMUM_INPUT_BYTES:
        raise CapacityAdmissionError(f"{label} must be non-empty and at most {MAXIMUM_INPUT_BYTES} bytes")
    return path.read_bytes()


def _load_one(path: Path, label: str) -> dict[str, Any]:
    payload = _read_regular(path, label)
    try:
        documents = list(yaml.load_all(payload.decode("utf-8"), Loader=UniqueKeyLoader))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CapacityAdmissionError(f"{label} is not valid duplicate-free UTF-8 YAML") from exc
    documents = [item for item in documents if item is not None]
    if len(documents) != 1:
        raise CapacityAdmissionError(f"{label} must contain exactly one YAML document")
    return _mapping(documents[0], label)


def _load_render(path: Path, expected_sha256: str, label: str) -> list[dict[str, Any]]:
    payload = _read_regular(path, label)
    if not SHA256.fullmatch(expected_sha256) or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise CapacityAdmissionError(f"{label} checksum does not match the capacity contract")
    try:
        documents = list(yaml.load_all(payload.decode("utf-8"), Loader=UniqueKeyLoader))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CapacityAdmissionError(f"{label} is not valid duplicate-free UTF-8 YAML") from exc
    result = [_mapping(item, f"{label} document") for item in documents if item is not None]
    if not result:
        raise CapacityAdmissionError(f"{label} contains no Kubernetes objects")
    return result


def _decimal(value: str, label: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CapacityAdmissionError(f"{label} is not a valid Kubernetes quantity") from exc
    if not result.is_finite() or result < 0:
        raise CapacityAdmissionError(f"{label} must be finite and non-negative")
    return result


def cpu_millicores(value: Any, label: str) -> int:
    text = str(value)
    match = CPU_QUANTITY.fullmatch(text)
    if match is None:
        raise CapacityAdmissionError(f"{label} is not a supported CPU quantity")
    multipliers = {"": Decimal(1000), "m": Decimal(1), "u": Decimal("0.001"), "n": Decimal("0.000001")}
    result = _decimal(match.group(1), label) * multipliers[match.group(2)]
    if result != result.to_integral_value():
        raise CapacityAdmissionError(f"{label} must resolve to whole millicores")
    return int(result)


def memory_bytes(value: Any, label: str) -> int:
    text = str(value)
    match = BYTE_QUANTITY.fullmatch(text)
    if match is None:
        raise CapacityAdmissionError(f"{label} is not a supported byte quantity")
    binary = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6}
    decimal = {"K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4, "P": 1000**5, "E": 1000**6, "": 1}
    suffix = match.group(2)
    multiplier = binary.get(suffix, decimal.get(suffix))
    if multiplier is None:
        raise CapacityAdmissionError(f"{label} has an unsupported byte suffix")
    result = _decimal(match.group(1), label) * multiplier
    if result != result.to_integral_value():
        raise CapacityAdmissionError(f"{label} must resolve to whole bytes")
    return int(result)


def _container_resources(container: dict[str, Any], label: str) -> PodResources:
    resources = _mapping(container.get("resources"), f"{label} resources")
    required = ("cpu", "memory")
    requests_value = resources.get("requests")
    limits_value = resources.get("limits")
    if not isinstance(requests_value, dict) or not isinstance(limits_value, dict):
        raise CapacityAdmissionError(f"{label} must set CPU and memory requests and limits")
    requests = _mapping(requests_value, f"{label} requests")
    limits = _mapping(limits_value, f"{label} limits")
    if any(key not in requests or key not in limits for key in required):
        raise CapacityAdmissionError(f"{label} must set CPU and memory requests and limits")
    result = PodResources(
        cpu_millicores(requests["cpu"], f"{label} CPU request"),
        memory_bytes(requests["memory"], f"{label} memory request"),
        cpu_millicores(limits["cpu"], f"{label} CPU limit"),
        memory_bytes(limits["memory"], f"{label} memory limit"),
    )
    if (
        result.limit_cpu_millicores < result.request_cpu_millicores
        or result.limit_memory_bytes < result.request_memory_bytes
    ):
        raise CapacityAdmissionError(f"{label} limit is below its request")
    return result


def _max_resources(left: PodResources, right: PodResources) -> PodResources:
    return PodResources(
        max(left.request_cpu_millicores, right.request_cpu_millicores),
        max(left.request_memory_bytes, right.request_memory_bytes),
        max(left.limit_cpu_millicores, right.limit_cpu_millicores),
        max(left.limit_memory_bytes, right.limit_memory_bytes),
    )


def effective_pod_resources(spec: dict[str, Any], label: str) -> PodResources:
    containers = [_mapping(item, f"{label} container") for item in _list(spec.get("containers"), f"{label} containers")]
    if not containers:
        raise CapacityAdmissionError(f"{label} must contain at least one application container")
    application = ZERO_RESOURCES
    for index, container in enumerate(containers):
        application = application.plus(_container_resources(container, f"{label} container {index}"))

    restartable = ZERO_RESOURCES
    maximum_init = ZERO_RESOURCES
    init_containers = spec.get("initContainers", [])
    for index, item in enumerate(_list(init_containers, f"{label} initContainers")):
        container = _mapping(item, f"{label} init container")
        resources = _container_resources(container, f"{label} init container {index}")
        if container.get("restartPolicy") == "Always":
            restartable = restartable.plus(resources)
            maximum_init = _max_resources(maximum_init, restartable)
        else:
            maximum_init = _max_resources(maximum_init, restartable.plus(resources))

    effective = _max_resources(application.plus(restartable), maximum_init)
    overhead = spec.get("overhead")
    if overhead is not None:
        overhead_map = _mapping(overhead, f"{label} overhead")
        if set(overhead_map) - {"cpu", "memory"}:
            raise CapacityAdmissionError(f"{label} has unsupported pod overhead resources")
        overhead_resources = PodResources(
            cpu_millicores(overhead_map.get("cpu", "0"), f"{label} CPU overhead"),
            memory_bytes(overhead_map.get("memory", "0"), f"{label} memory overhead"),
            cpu_millicores(overhead_map.get("cpu", "0"), f"{label} CPU overhead"),
            memory_bytes(overhead_map.get("memory", "0"), f"{label} memory overhead"),
        )
        effective = effective.plus(overhead_resources)
    return effective


def _int_or_percentage(value: Any, basis: int, label: str, round_up: bool) -> int:
    if isinstance(value, bool):
        raise CapacityAdmissionError(f"{label} must be an integer or percentage")
    if isinstance(value, int):
        if value < 0:
            raise CapacityAdmissionError(f"{label} cannot be negative")
        return value
    text = str(value)
    if not text.endswith("%") or not text[:-1].isdigit():
        raise CapacityAdmissionError(f"{label} must be an integer or percentage")
    percentage = int(text[:-1])
    scaled = basis * percentage / 100
    return math.ceil(scaled) if round_up else math.floor(scaled)


def _workload_replicas(document: dict[str, Any], node_count: int, label: str) -> tuple[int, int, dict[str, Any]]:
    kind = document["kind"]
    spec = _mapping(document.get("spec"), f"{label} spec")
    if kind == "Pod":
        return 1, 1, spec
    template = _mapping(spec.get("template"), f"{label} template")
    pod_spec = _mapping(template.get("spec"), f"{label} pod spec")
    if kind == "Deployment":
        replicas = _integer(spec.get("replicas", 1), f"{label} replicas")
        strategy = _mapping(spec.get("strategy", {}), f"{label} strategy")
        strategy_type = strategy.get("type", "RollingUpdate")
        if strategy_type == "Recreate":
            return replicas, replicas, pod_spec
        if strategy_type != "RollingUpdate":
            raise CapacityAdmissionError(f"{label} has unsupported Deployment strategy")
        rolling = _mapping(strategy.get("rollingUpdate", {}), f"{label} rollingUpdate")
        surge = _int_or_percentage(rolling.get("maxSurge", "25%"), replicas, f"{label} maxSurge", True)
        return replicas, replicas + surge, pod_spec
    if kind == "StatefulSet":
        replicas = _integer(spec.get("replicas", 1), f"{label} replicas")
        strategy = _mapping(spec.get("updateStrategy", {}), f"{label} updateStrategy")
        if strategy.get("type", "RollingUpdate") not in ("RollingUpdate", "OnDelete"):
            raise CapacityAdmissionError(f"{label} has unsupported StatefulSet strategy")
        return replicas, replicas, pod_spec
    if kind == "DaemonSet":
        strategy = _mapping(spec.get("updateStrategy", {}), f"{label} updateStrategy")
        if strategy.get("type", "RollingUpdate") == "OnDelete":
            return node_count, node_count, pod_spec
        if strategy.get("type", "RollingUpdate") != "RollingUpdate":
            raise CapacityAdmissionError(f"{label} has unsupported DaemonSet strategy")
        rolling = _mapping(strategy.get("rollingUpdate", {}), f"{label} rollingUpdate")
        surge = _int_or_percentage(rolling.get("maxSurge", 0), node_count, f"{label} maxSurge", True)
        return node_count, node_count + surge, pod_spec
    if kind == "Job":
        parallelism = _integer(spec.get("parallelism", 1), f"{label} parallelism", 1)
        return 0, parallelism, pod_spec
    raise AssertionError("unreachable")


def _pvc_bytes(
    pvc_spec: dict[str, Any],
    storage_classes: dict[str, dict[str, Any]],
    multiplicity: int,
    label: str,
) -> tuple[int, int, int]:
    storage_class = pvc_spec.get("storageClassName")
    if not isinstance(storage_class, str) or storage_class not in storage_classes:
        raise CapacityAdmissionError(f"{label} must use a capacity-modeled StorageClass")
    resources = _mapping(pvc_spec.get("resources"), f"{label} resources")
    requests = _mapping(resources.get("requests"), f"{label} requests")
    if "storage" not in requests:
        raise CapacityAdmissionError(f"{label} must request storage")
    logical = memory_bytes(requests["storage"], f"{label} storage") * multiplicity
    storage = storage_classes[storage_class]
    replicas = _integer(storage.get("replicas"), f"{storage_class} replicas", 1)
    surviving = _integer(
        storage.get("replicas_after_one_node_loss"),
        f"{storage_class} replicas after one-node loss",
        1,
    )
    if surviving >= replicas:
        raise CapacityAdmissionError(f"{storage_class} must lose at least one replica with one node")
    return logical, logical * replicas, logical * surviving


def component_capacity(
    documents: list[dict[str, Any]],
    item: dict[str, Any],
    node_count: int,
    storage_classes: dict[str, dict[str, Any]],
    component: str,
    identities: set[tuple[str, str, str, str]],
) -> ComponentCapacity:
    steady = ZERO_RESOURCES
    peak = ZERO_RESOURCES
    workload_count = 0
    pvc_count = 0
    logical_pvc_bytes = 0
    raw_pvc_bytes = 0
    loss_pvc_bytes = 0

    for document in documents:
        api_version = document.get("apiVersion")
        kind = document.get("kind")
        metadata = _mapping(document.get("metadata"), f"{component} object metadata")
        name = metadata.get("name")
        namespace = metadata.get("namespace", "")
        if not all(isinstance(value, str) and value for value in (api_version, kind, name)):
            raise CapacityAdmissionError(f"{component} render contains an object without exact identity")
        group = api_version.split("/", 1)[0] if "/" in api_version else "core"
        identity = (api_version, kind, str(namespace), name)
        if identity in identities:
            raise CapacityAdmissionError("rendered Kubernetes object has more than one owner")
        identities.add(identity)
        if (group, kind) in CAPACITY_BEARING_UNSUPPORTED_KINDS:
            raise CapacityAdmissionError(
                f"{component} render contains unsupported capacity-bearing kind {kind}"
            )
        if kind in ("CronJob", "ReplicationController", "ReplicaSet"):
            raise CapacityAdmissionError(f"{component} render contains unsupported workload kind {kind}")
        if kind in STANDARD_WORKLOAD_KINDS:
            workload_count += 1
            steady_replicas, peak_replicas, pod_spec = _workload_replicas(
                document, node_count, f"{component} {kind}"
            )
            per_pod = effective_pod_resources(pod_spec, f"{component} {kind}")
            steady = steady.plus(per_pod.scaled(steady_replicas))
            peak = peak.plus(per_pod.scaled(peak_replicas))
            if kind == "StatefulSet":
                spec = _mapping(document.get("spec"), f"{component} StatefulSet spec")
                templates = _list(
                    spec.get("volumeClaimTemplates", []),
                    f"{component} volumeClaimTemplates",
                )
                for index, template in enumerate(templates):
                    pvc_count += 1
                    pvc_spec = _mapping(
                        _mapping(template, f"{component} PVC template").get("spec"),
                        f"{component} PVC template spec",
                    )
                    logical, raw, loss = _pvc_bytes(
                        pvc_spec,
                        storage_classes,
                        steady_replicas,
                        f"{component} PVC template {index}",
                    )
                    logical_pvc_bytes += logical
                    raw_pvc_bytes += raw
                    loss_pvc_bytes += loss
        if kind == "PersistentVolumeClaim":
            pvc_count += 1
            pvc_spec = _mapping(document.get("spec"), f"{component} PVC spec")
            logical, raw, loss = _pvc_bytes(
                pvc_spec, storage_classes, 1, f"{component} PVC"
            )
            logical_pvc_bytes += logical
            raw_pvc_bytes += raw
            loss_pvc_bytes += loss

    expected_documents = _integer(item.get("expected_document_count"), f"{component} expected document count", 1)
    expected_workloads = _integer(item.get("expected_workload_count"), f"{component} expected workload count")
    expected_pvcs = _integer(item.get("expected_pvc_definition_count"), f"{component} expected PVC definition count")
    if len(documents) != expected_documents:
        raise CapacityAdmissionError(f"{component} rendered document count changed")
    if workload_count != expected_workloads:
        raise CapacityAdmissionError(f"{component} rendered workload count changed")
    if pvc_count != expected_pvcs:
        raise CapacityAdmissionError(f"{component} rendered PVC definition count changed")
    return ComponentCapacity(
        len(documents),
        workload_count,
        pvc_count,
        steady,
        peak,
        logical_pvc_bytes,
        raw_pvc_bytes,
        loss_pvc_bytes,
    )


def evaluate(contract: dict[str, Any], contract_path: Path) -> dict[str, int | str]:
    if contract.get("schema_version") != 1:
        raise CapacityAdmissionError("capacity contract schema_version must equal 1")
    if contract.get("admission_status") != "ready":
        raise CapacityAdmissionError(
            "admission_status must equal ready after every render and baseline input is verified"
        )
    baseline = _mapping(contract.get("baseline"), "baseline")
    node_count = _integer(baseline.get("node_count"), "baseline node count", 1)
    if node_count != 3:
        raise CapacityAdmissionError("Phase 6 Stage A baseline must contain exactly three nodes")
    numeric_baseline = {
        key: _integer(baseline.get(key), f"baseline {key}")
        for key in (
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
        )
    }
    if numeric_baseline["one_node_loss_allocatable_cpu_millicores"] >= numeric_baseline["allocatable_cpu_millicores"]:
        raise CapacityAdmissionError("one-node-loss CPU capacity must be below total capacity")
    if numeric_baseline["one_node_loss_allocatable_memory_bytes"] >= numeric_baseline["allocatable_memory_bytes"]:
        raise CapacityAdmissionError("one-node-loss memory capacity must be below total capacity")

    storage_classes_document = _mapping(contract.get("storage_classes"), "storage_classes")
    if not storage_classes_document:
        raise CapacityAdmissionError("at least one StorageClass capacity model is required")
    storage_classes = {
        str(name): _mapping(item, f"StorageClass {name}")
        for name, item in storage_classes_document.items()
    }
    components = _mapping(contract.get("components"), "components")
    if set(components) != REQUIRED_COMPONENTS:
        raise CapacityAdmissionError("capacity contract must contain the exact mandatory Phase 6 component set")

    aggregate_steady = ZERO_RESOURCES
    aggregate_peak = ZERO_RESOURCES
    document_count = 0
    workload_count = 0
    pvc_count = 0
    logical_pvc_bytes = 0
    raw_pvc_bytes = 0
    loss_pvc_bytes = 0
    identities: set[tuple[str, str, str, str]] = set()
    base = contract_path.resolve().parent
    for component in sorted(REQUIRED_COMPONENTS):
        item = _mapping(components[component], f"component {component}")
        render_path_value = item.get("render_path")
        render_sha256 = item.get("render_sha256")
        if not isinstance(render_path_value, str) or not render_path_value:
            raise CapacityAdmissionError(f"component {component} has no render_path")
        if not isinstance(render_sha256, str) or not SHA256.fullmatch(render_sha256):
            raise CapacityAdmissionError(f"component {component} has no exact render_sha256")
        render_path = Path(render_path_value)
        if not render_path.is_absolute():
            render_path = (base / render_path).resolve()
        capacity = component_capacity(
            _load_render(render_path, render_sha256, f"component {component} render"),
            item,
            node_count,
            storage_classes,
            component,
            identities,
        )
        document_count += capacity.document_count
        workload_count += capacity.workload_count
        pvc_count += capacity.pvc_definition_count
        aggregate_steady = aggregate_steady.plus(capacity.steady)
        aggregate_peak = aggregate_peak.plus(capacity.peak)
        logical_pvc_bytes += capacity.logical_pvc_bytes
        raw_pvc_bytes += capacity.raw_pvc_bytes
        loss_pvc_bytes += capacity.one_node_loss_pvc_bytes

    post_steady_cpu = numeric_baseline["existing_requested_cpu_millicores"] + aggregate_steady.request_cpu_millicores
    post_steady_memory = numeric_baseline["existing_requested_memory_bytes"] + aggregate_steady.request_memory_bytes
    post_peak_cpu = numeric_baseline["existing_requested_cpu_millicores"] + aggregate_peak.request_cpu_millicores
    post_peak_memory = numeric_baseline["existing_requested_memory_bytes"] + aggregate_peak.request_memory_bytes
    cpu_headroom = numeric_baseline["one_node_loss_allocatable_cpu_millicores"] - post_peak_cpu
    memory_headroom = numeric_baseline["one_node_loss_allocatable_memory_bytes"] - post_peak_memory
    storage_headroom = numeric_baseline["storage_available_bytes"] - raw_pvc_bytes
    loss_storage_headroom = numeric_baseline["worst_two_node_storage_available_bytes"] - loss_pvc_bytes

    if post_steady_cpu > numeric_baseline["allocatable_cpu_millicores"] or post_steady_memory > numeric_baseline["allocatable_memory_bytes"]:
        raise CapacityAdmissionError("steady-state Phase 6 requests exceed total cluster capacity")
    if cpu_headroom < numeric_baseline["required_cpu_reserve_millicores"]:
        raise CapacityAdmissionError("rollout peak violates one-node-loss CPU reserve")
    if memory_headroom < numeric_baseline["required_memory_reserve_bytes"]:
        raise CapacityAdmissionError("rollout peak violates one-node-loss memory reserve")
    if storage_headroom < numeric_baseline["required_storage_reserve_bytes"]:
        raise CapacityAdmissionError("PVC replicas violate total storage reserve")
    if loss_storage_headroom < numeric_baseline["required_storage_reserve_bytes"]:
        raise CapacityAdmissionError("PVC replicas violate one-node-loss storage reserve")

    return {
        "schema_version": 1,
        "status": "PASS",
        "component_count": len(REQUIRED_COMPONENTS),
        "rendered_document_count": document_count,
        "workload_definition_count": workload_count,
        "pvc_definition_count": pvc_count,
        "new_steady_cpu_millicores": aggregate_steady.request_cpu_millicores,
        "new_rollout_peak_cpu_millicores": aggregate_peak.request_cpu_millicores,
        "one_node_loss_rollout_cpu_headroom_millicores": cpu_headroom,
        "new_steady_memory_bytes": aggregate_steady.request_memory_bytes,
        "new_rollout_peak_memory_bytes": aggregate_peak.request_memory_bytes,
        "one_node_loss_rollout_memory_headroom_bytes": memory_headroom,
        "new_logical_pvc_bytes": logical_pvc_bytes,
        "new_raw_pvc_bytes": raw_pvc_bytes,
        "one_node_loss_pvc_bytes": loss_pvc_bytes,
        "storage_headroom_bytes": storage_headroom,
        "one_node_loss_storage_headroom_bytes": loss_storage_headroom,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = args.contract.resolve()
    try:
        report = evaluate(_load_one(contract_path, "capacity contract"), contract_path)
    except (CapacityAdmissionError, OSError) as exc:
        print(f"[FAIL] Phase 6 capacity admission: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
