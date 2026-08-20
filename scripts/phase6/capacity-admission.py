#!/usr/bin/env python3
"""Deterministic, fail-closed Phase 6 scheduling and PVC admission gate.

The gate consumes only checksum-bound, offline Helm/Kustomize render outputs. It
does not invoke Helm, kubectl, a cloud API, or the live cluster. The tracked
contract intentionally remains blocked until every mandatory component render
and the exact sanitized baseline are supplied.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
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
ALLOWED_NON_CAPACITY_KINDS = frozenset(
    {
        ("admissionregistration.k8s.io/v1", "MutatingWebhookConfiguration"),
        ("admissionregistration.k8s.io/v1", "ValidatingWebhookConfiguration"),
        ("apiextensions.k8s.io/v1", "CustomResourceDefinition"),
        ("bitnami.com/v1alpha1", "SealedSecret"),
        ("cert-manager.io/v1", "Certificate"),
        ("cert-manager.io/v1", "Issuer"),
        ("cilium.io/v2", "CiliumNetworkPolicy"),
        ("monitoring.coreos.com/v1", "PodMonitor"),
        ("monitoring.coreos.com/v1", "PrometheusRule"),
        ("monitoring.coreos.com/v1", "ServiceMonitor"),
        ("networking.k8s.io/v1", "Ingress"),
        ("networking.k8s.io/v1", "NetworkPolicy"),
        ("policy/v1", "PodDisruptionBudget"),
        ("rbac.authorization.k8s.io/v1", "ClusterRole"),
        ("rbac.authorization.k8s.io/v1", "ClusterRoleBinding"),
        ("rbac.authorization.k8s.io/v1", "Role"),
        ("rbac.authorization.k8s.io/v1", "RoleBinding"),
        ("scheduling.k8s.io/v1", "PriorityClass"),
        ("v1", "ConfigMap"),
        ("v1", "LimitRange"),
        ("v1", "Namespace"),
        ("v1", "ResourceQuota"),
        ("v1", "Secret"),
        ("v1", "Service"),
        ("v1", "ServiceAccount"),
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
UniqueKeyLoader.add_constructor(
    "tag:yaml.org,2002:value",
    lambda loader, node: loader.construct_scalar(node),
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


@dataclass(frozen=True)
class NodeCapacity:
    cpu_millicores: int
    memory_bytes: int
    storage_available_bytes: int
    labels: dict[str, str]
    taints: tuple[tuple[str, str, str], ...]


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


def _bound_input(
    contract_path: Path, binding: Any, label: str
) -> tuple[Path, dict[str, Any]]:
    item = _mapping(binding, f"{label} binding")
    if set(item) != {"path", "sha256"}:
        raise CapacityAdmissionError(f"{label} binding must contain exactly path and sha256")
    path_value = item.get("path")
    expected = item.get("sha256")
    if not isinstance(path_value, str) or not path_value or Path(path_value).is_absolute():
        raise CapacityAdmissionError(f"{label} binding path must be relative")
    if not isinstance(expected, str) or not SHA256.fullmatch(expected) or expected == "0" * 64:
        raise CapacityAdmissionError(f"{label} binding has no exact SHA-256")
    path = (contract_path.parent / path_value).resolve()
    payload = _read_regular(path, label)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise CapacityAdmissionError(f"{label} checksum does not match")
    return path, _load_one(path, label)


def _identity_free_nodes(document: dict[str, Any], label: str) -> tuple[list[NodeCapacity], dict[str, int]]:
    if document.get("schema_version") != 1 or document.get("protection") != "identity-free-sanitized":
        raise CapacityAdmissionError(f"{label} is not identity-free protected evidence")
    if set(document) != {"schema_version", "protection", "source_snapshots", "nodes", "existing_requests"}:
        raise CapacityAdmissionError(f"{label} has missing or unexpected fields")
    snapshots = _mapping(document.get("source_snapshots"), f"{label} source snapshots")
    if set(snapshots) != {"node_sha256", "pod_sha256", "phase5_argocd_render_sha256", "phase5_cert_manager_render_sha256", "phase5_longhorn_render_sha256"} or any(
        not isinstance(value, str) or not SHA256.fullmatch(value) or value == "0" * 64
        for value in snapshots.values()
    ):
        raise CapacityAdmissionError(f"{label} source snapshots are not checksum-bound")
    forbidden = {"name", "uid", "hostname", "provider_id", "providerID", "address", "ip"}
    if any(key in document for key in forbidden):
        raise CapacityAdmissionError(f"{label} contains a forbidden identity field")
    raw_nodes = _list(document.get("nodes"), f"{label} nodes")
    if len(raw_nodes) != 3:
        raise CapacityAdmissionError(f"{label} must contain exactly three anonymous nodes")
    nodes: list[NodeCapacity] = []
    for index, raw in enumerate(raw_nodes):
        node = _mapping(raw, f"{label} node {index}")
        if any(key in node for key in forbidden):
            raise CapacityAdmissionError(f"{label} node contains a forbidden identity field")
        if set(node) != {"allocatable_cpu_millicores", "allocatable_memory_bytes", "storage_available_bytes", "labels", "taints"}:
            raise CapacityAdmissionError(f"{label} node has missing or unexpected fields")
        labels = _mapping(node["labels"], f"{label} node labels")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items()):
            raise CapacityAdmissionError(f"{label} node labels must be strings")
        taints_raw = _list(node["taints"], f"{label} node taints")
        taints: list[tuple[str, str, str]] = []
        for taint_raw in taints_raw:
            taint = _mapping(taint_raw, f"{label} node taint")
            if set(taint) != {"key", "value", "effect"} or taint.get("effect") not in {"NoSchedule", "NoExecute", "PreferNoSchedule"}:
                raise CapacityAdmissionError(f"{label} node taint is unsupported")
            if not isinstance(taint.get("key"), str) or not isinstance(taint.get("value"), str):
                raise CapacityAdmissionError(f"{label} node taint is invalid")
            taints.append((taint["key"], taint["value"], taint["effect"]))
        nodes.append(
            NodeCapacity(
                _integer(node["allocatable_cpu_millicores"], f"{label} node CPU", 1),
                _integer(node["allocatable_memory_bytes"], f"{label} node memory", 1),
                _integer(node["storage_available_bytes"], f"{label} node storage", 1),
                dict(labels),
                tuple(taints),
            )
        )
    aggregates = _mapping(document.get("existing_requests", {}), f"{label} existing requests")
    return nodes, {
        "existing_requested_cpu_millicores": _integer(aggregates.get("cpu_millicores", 0), f"{label} existing CPU"),
        "raw_requested_memory_bytes": _integer(aggregates.get("raw_memory_bytes", 0), f"{label} raw memory"),
        "phase5_render_requested_memory_bytes": _integer(aggregates.get("phase5_render_memory_bytes", 0), f"{label} Phase 5 memory"),
    }


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


def _container_resources(container: dict[str, Any], label: str, allow_missing_requests: bool = False) -> PodResources:
    resources_value = container.get("resources")
    if resources_value is None and allow_missing_requests:
        resources_value = {}
    resources = _mapping(resources_value, f"{label} resources")
    required = ("cpu", "memory")
    requests_value = resources.get("requests")
    limits_value = resources.get("limits", {})
    if requests_value is None and allow_missing_requests:
        requests_value = {}
    if not isinstance(requests_value, dict) or not isinstance(limits_value, dict):
        raise CapacityAdmissionError(f"{label} must set CPU and memory requests; limits must be a mapping when present")
    requests = _mapping(requests_value, f"{label} requests")
    limits = _mapping(limits_value, f"{label} limits")
    if any(key not in requests for key in required) and not allow_missing_requests:
        raise CapacityAdmissionError(f"{label} must set CPU and memory requests")
    request_cpu = cpu_millicores(requests.get("cpu", "0"), f"{label} CPU request")
    request_memory = memory_bytes(requests.get("memory", "0"), f"{label} memory request")
    limit_cpu = cpu_millicores(limits["cpu"], f"{label} CPU limit") if "cpu" in limits else 0
    limit_memory = memory_bytes(limits["memory"], f"{label} memory limit") if "memory" in limits else 0
    result = PodResources(
        request_cpu,
        request_memory,
        limit_cpu,
        limit_memory,
    )
    if (
        ("cpu" in limits and result.limit_cpu_millicores < result.request_cpu_millicores)
        or ("memory" in limits and result.limit_memory_bytes < result.request_memory_bytes)
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


def effective_pod_resources(spec: dict[str, Any], label: str, allow_missing_requests: bool = False) -> PodResources:
    containers = [_mapping(item, f"{label} container") for item in _list(spec.get("containers"), f"{label} containers")]
    if not containers:
        raise CapacityAdmissionError(f"{label} must contain at least one application container")
    application = ZERO_RESOURCES
    for index, container in enumerate(containers):
        application = application.plus(_container_resources(container, f"{label} container {index}", allow_missing_requests))

    restartable = ZERO_RESOURCES
    maximum_init = ZERO_RESOURCES
    init_containers = spec.get("initContainers", [])
    for index, item in enumerate(_list(init_containers, f"{label} initContainers")):
        container = _mapping(item, f"{label} init container")
        resources = _container_resources(container, f"{label} init container {index}", allow_missing_requests)
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


def _tolerates(taint: tuple[str, str, str], tolerations: list[Any], label: str) -> bool:
    key, value, effect = taint
    if effect == "PreferNoSchedule":
        return True
    for raw in tolerations:
        item = _mapping(raw, f"{label} toleration")
        operator = item.get("operator", "Equal")
        if operator not in {"Equal", "Exists"}:
            raise CapacityAdmissionError(f"{label} has an unsupported toleration operator")
        if item.get("effect") not in (None, effect) or item.get("key") != key:
            continue
        if operator == "Exists" or item.get("value", "") == value:
            return True
    return False


def _node_term_matches(labels: dict[str, str], raw: Any, label: str) -> bool:
    term = _mapping(raw, f"{label} node selector term")
    if term.get("matchFields"):
        raise CapacityAdmissionError(f"{label} matchFields are unsupported")
    expressions = _list(term.get("matchExpressions", []), f"{label} matchExpressions")
    for raw_expression in expressions:
        expression = _mapping(raw_expression, f"{label} node selector expression")
        key = expression.get("key")
        operator = expression.get("operator")
        values = expression.get("values", [])
        if not isinstance(key, str) or operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            raise CapacityAdmissionError(f"{label} has an unsupported node-affinity expression")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise CapacityAdmissionError(f"{label} node-affinity values must be strings")
        present = key in labels
        if operator == "In" and (not present or labels[key] not in values):
            return False
        if operator == "NotIn" and present and labels[key] in values:
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
    return True


def _eligible_nodes(pod_spec: dict[str, Any], nodes: list[NodeCapacity], label: str) -> list[NodeCapacity]:
    selector = _mapping(pod_spec.get("nodeSelector", {}), f"{label} nodeSelector")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in selector.items()):
        raise CapacityAdmissionError(f"{label} nodeSelector must contain strings")
    tolerations = _list(pod_spec.get("tolerations", []), f"{label} tolerations")
    for raw in tolerations:
        item = _mapping(raw, f"{label} toleration")
        if item.get("operator", "Equal") not in {"Equal", "Exists"}:
            raise CapacityAdmissionError(f"{label} has an unsupported toleration operator")
    affinity = _mapping(pod_spec.get("affinity", {}), f"{label} affinity")
    pod_affinity = affinity.get("podAffinity")
    if isinstance(pod_affinity, dict) and pod_affinity.get("requiredDuringSchedulingIgnoredDuringExecution"):
        raise CapacityAdmissionError(f"{label} required podAffinity is unsupported")
    node_affinity = _mapping(affinity.get("nodeAffinity", {}), f"{label} nodeAffinity")
    required = node_affinity.get("requiredDuringSchedulingIgnoredDuringExecution")
    terms: list[Any] | None = None
    if required is not None:
        terms = _list(_mapping(required, f"{label} required nodeAffinity").get("nodeSelectorTerms"), f"{label} nodeSelectorTerms")
        if not terms:
            raise CapacityAdmissionError(f"{label} required nodeAffinity has no terms")
    for constraint in _list(pod_spec.get("topologySpreadConstraints", []), f"{label} topologySpreadConstraints"):
        item = _mapping(constraint, f"{label} topology spread constraint")
        if item.get("whenUnsatisfiable") == "DoNotSchedule" and (
            item.get("topologyKey") != "kubernetes.io/hostname"
            or _integer(item.get("maxSkew"), f"{label} topology maxSkew", 1) != 1
        ):
            raise CapacityAdmissionError(f"{label} hard topology spread is unsupported")
    eligible = []
    for node in nodes:
        if any(node.labels.get(key) != value for key, value in selector.items()):
            continue
        if any(not _tolerates(taint, tolerations, label) for taint in node.taints):
            continue
        if terms is not None and not any(_node_term_matches(node.labels, term, label) for term in terms):
            continue
        eligible.append(node)
    if not eligible:
        raise CapacityAdmissionError(f"{label} has no eligible candidate node")
    return eligible


def _placement_check(
    pod: PodResources,
    steady_replicas: int,
    peak_replicas: int,
    pod_spec: dict[str, Any],
    nodes: list[NodeCapacity],
    label: str,
) -> int:
    eligible = _eligible_nodes(pod_spec, nodes, label)
    minimum_cpu = min(node.cpu_millicores for node in eligible)
    minimum_memory = min(node.memory_bytes for node in eligible)
    if pod.request_cpu_millicores > minimum_cpu or pod.request_memory_bytes > minimum_memory:
        raise CapacityAdmissionError(f"{label} largest eligible pod does not fit a candidate node")
    affinity = _mapping(pod_spec.get("affinity", {}), f"{label} affinity")
    anti = _mapping(affinity.get("podAntiAffinity", {}), f"{label} podAntiAffinity")
    required_anti = _list(anti.get("requiredDuringSchedulingIgnoredDuringExecution", []), f"{label} required podAntiAffinity")
    for term_raw in required_anti:
        term = _mapping(term_raw, f"{label} required podAntiAffinity term")
        if term.get("topologyKey") != "kubernetes.io/hostname" or not isinstance(term.get("labelSelector"), dict):
            raise CapacityAdmissionError(f"{label} required podAntiAffinity is unsupported")
    if required_anti and steady_replicas > len(eligible):
        raise CapacityAdmissionError(f"{label} required podAntiAffinity is infeasible")
    per_node = math.ceil(peak_replicas / len(eligible)) if peak_replicas else 0
    if pod.request_cpu_millicores * per_node > minimum_cpu or pod.request_memory_bytes * per_node > minimum_memory:
        raise CapacityAdmissionError(f"{label} conservative per-node placement is infeasible")
    if len(nodes) > 1 and peak_replicas:
        for lost in nodes:
            remaining = [node for node in eligible if node is not lost]
            if not remaining:
                raise CapacityAdmissionError(f"{label} has no eligible node after one-node loss")
            loss_per_node = math.ceil(peak_replicas / len(remaining))
            if pod.request_cpu_millicores * loss_per_node > min(node.cpu_millicores for node in remaining) or pod.request_memory_bytes * loss_per_node > min(node.memory_bytes for node in remaining):
                raise CapacityAdmissionError(f"{label} one-node-loss placement is infeasible")
    return len(eligible)


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
    surviving = replicas - 1
    return logical, logical * replicas, logical * surviving


def _storage_classes(contract: dict[str, Any], contract_path: Path) -> dict[str, dict[str, Any]]:
    binding = _mapping(contract.get("storage_class_manifest"), "Longhorn StorageClass manifest binding")
    if set(binding) != {"path", "sha256"}:
        raise CapacityAdmissionError("Longhorn StorageClass manifest binding must contain exactly path and sha256")
    if not isinstance(binding.get("path"), str) or Path(binding["path"]).is_absolute():
        raise CapacityAdmissionError("Longhorn StorageClass manifest path must be relative")
    if not isinstance(binding.get("sha256"), str) or not SHA256.fullmatch(binding["sha256"]):
        raise CapacityAdmissionError("Longhorn StorageClass manifest has no exact SHA-256")
    path = (contract_path.parent / binding["path"]).resolve()
    documents = _load_render(path, binding["sha256"], "Longhorn StorageClass manifest")
    result: dict[str, dict[str, Any]] = {}
    for item in documents:
        if item.get("apiVersion") != "storage.k8s.io/v1" or item.get("kind") != "StorageClass":
            raise CapacityAdmissionError("Longhorn StorageClass manifest contains an unexpected kind")
        metadata = _mapping(item.get("metadata"), "Longhorn StorageClass metadata")
        name = metadata.get("name")
        parameters = _mapping(item.get("parameters"), f"StorageClass {name} parameters")
        if not isinstance(name, str) or name not in {"longhorn-critical", "longhorn-standard"}:
            raise CapacityAdmissionError("Longhorn StorageClass inventory is unexpected")
        replicas = parameters.get("numberOfReplicas")
        if not isinstance(replicas, str) or not replicas.isdigit():
            raise CapacityAdmissionError(f"StorageClass {name} has no exact replica count")
        result[name] = {"replicas": int(replicas)}
    if set(result) != {"longhorn-critical", "longhorn-standard"}:
        raise CapacityAdmissionError("Longhorn StorageClass inventory is incomplete")
    return result


def component_capacity(
    documents: list[dict[str, Any]],
    item: dict[str, Any],
    node_count: int,
    storage_classes: dict[str, dict[str, Any]],
    component: str,
    identities: set[tuple[str, str, str, str]],
    allow_missing_requests: bool = False,
    candidate_nodes: list[NodeCapacity] | None = None,
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
        identity = (api_version, kind, str(namespace), name)
        if identity in identities:
            raise CapacityAdmissionError("rendered Kubernetes object has more than one owner")
        identities.add(identity)
        if kind == "List" or (kind not in STANDARD_WORKLOAD_KINDS and kind != "PersistentVolumeClaim" and (api_version, kind) not in ALLOWED_NON_CAPACITY_KINDS):
            raise CapacityAdmissionError(f"{component} render contains unknown or workload-producing kind {kind}")
        if kind in STANDARD_WORKLOAD_KINDS:
            workload_count += 1
            steady_replicas, peak_replicas, pod_spec = _workload_replicas(
                document, node_count, f"{component} {kind}"
            )
            per_pod = effective_pod_resources(pod_spec, f"{component} {kind}", allow_missing_requests)
            if candidate_nodes is not None:
                eligible_count = _placement_check(per_pod, steady_replicas, peak_replicas, pod_spec, candidate_nodes, f"{component} {kind}")
                if kind == "DaemonSet":
                    steady_replicas = eligible_count
                    strategy = _mapping(_mapping(document.get("spec"), f"{component} DaemonSet spec").get("updateStrategy", {}), f"{component} DaemonSet strategy")
                    rolling = _mapping(strategy.get("rollingUpdate", {}), f"{component} DaemonSet rollingUpdate")
                    peak_replicas = eligible_count + _int_or_percentage(rolling.get("maxSurge", 0), eligible_count, f"{component} DaemonSet maxSurge", True)
                    _placement_check(per_pod, steady_replicas, peak_replicas, pod_spec, candidate_nodes, f"{component} DaemonSet")
            annotations_value = metadata.get("annotations")
            annotations = {} if annotations_value is None else _mapping(annotations_value, f"{component} annotations")
            projection_mode = annotations.get("capacity.platform.verda.io/mode", "normal")
            if projection_mode not in {"normal", "peak-only"}:
                raise CapacityAdmissionError(f"{component} has an unsupported capacity projection mode")
            if projection_mode != "peak-only":
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


def evaluate(contract: dict[str, Any], contract_path: Path) -> dict[str, Any]:
    if contract.get("schema_version") != 1:
        raise CapacityAdmissionError("capacity contract schema_version must equal 1")
    if contract.get("admission_status") != "ready":
        raise CapacityAdmissionError(
            "admission_status must equal ready after every render and baseline input is verified"
        )
    projection_only = contract.get("_projection_only") is True
    evidence_bindings = _mapping(contract.get("protected_evidence"), "protected_evidence")
    if set(evidence_bindings) != {"baseline", "candidate"}:
        raise CapacityAdmissionError("protected_evidence must bind baseline and candidate inputs")
    _, baseline_evidence = _bound_input(contract_path, evidence_bindings["baseline"], "protected baseline evidence")
    baseline_nodes, observed = _identity_free_nodes(baseline_evidence, "protected baseline evidence")
    if projection_only:
        candidate_nodes = baseline_nodes
    else:
        _, candidate_evidence = _bound_input(contract_path, evidence_bindings["candidate"], "protected candidate evidence")
        candidate_nodes, _ = _identity_free_nodes(candidate_evidence, "protected candidate evidence")
    node_count = len(baseline_nodes)
    if len(candidate_nodes) != node_count:
        raise CapacityAdmissionError("candidate evidence must contain the same three-node topology")
    required_reserve = _mapping(contract.get("required_reserve"), "required_reserve")
    if set(required_reserve) != {"cpu_millicores", "memory_bytes", "storage_bytes"}:
        raise CapacityAdmissionError("required_reserve has missing or unexpected fields")
    baseline = _mapping(contract.get("baseline"), "baseline")
    derived_baseline = {
        "node_count": node_count,
        "allocatable_cpu_millicores": sum(node.cpu_millicores for node in baseline_nodes),
        "allocatable_memory_bytes": sum(node.memory_bytes for node in baseline_nodes),
        "one_node_loss_allocatable_cpu_millicores": sum(sorted(node.cpu_millicores for node in baseline_nodes)[:2]),
        "one_node_loss_allocatable_memory_bytes": sum(sorted(node.memory_bytes for node in baseline_nodes)[:2]),
        "existing_requested_cpu_millicores": observed["existing_requested_cpu_millicores"],
        "existing_requested_memory_bytes": observed["raw_requested_memory_bytes"] + observed["phase5_render_requested_memory_bytes"],
        "required_cpu_reserve_millicores": _integer(required_reserve["cpu_millicores"], "required CPU reserve"),
        "required_memory_reserve_bytes": _integer(required_reserve["memory_bytes"], "required memory reserve"),
        "storage_available_bytes": sum(node.storage_available_bytes for node in baseline_nodes),
        "worst_two_node_storage_available_bytes": sum(sorted(node.storage_available_bytes for node in baseline_nodes)[:2]),
        "required_storage_reserve_bytes": _integer(required_reserve["storage_bytes"], "required storage reserve"),
    }
    if baseline != derived_baseline:
        raise CapacityAdmissionError("baseline does not match checksum-bound protected evidence")
    numeric_baseline = derived_baseline
    snapshots = _mapping(baseline_evidence["source_snapshots"], "protected baseline source snapshots")
    derived_provenance = {
        "raw_snapshot_kind": "sanitized-phase5-node-and-pod-json",
        "node_snapshot_sha256": snapshots["node_sha256"],
        "pod_snapshot_sha256": snapshots["pod_sha256"],
        "raw_requested_memory_bytes": observed["raw_requested_memory_bytes"],
        "phase5_render_requested_memory_bytes": observed["phase5_render_requested_memory_bytes"],
        "phase5_render_sha256": {
            "argocd": snapshots["phase5_argocd_render_sha256"],
            "cert_manager": snapshots["phase5_cert_manager_render_sha256"],
            "longhorn": snapshots["phase5_longhorn_render_sha256"],
        },
        "post_phase5_cpu_source": "protected-phase5-identity-free-reducer",
        "post_phase5_memory_source": "exact-raw-baseline-plus-checksum-bound-phase5-render-delta",
    }
    if _mapping(contract.get("baseline_provenance"), "baseline_provenance") != derived_provenance:
        raise CapacityAdmissionError("baseline_provenance does not match protected evidence")
    if numeric_baseline["one_node_loss_allocatable_cpu_millicores"] >= numeric_baseline["allocatable_cpu_millicores"]:
        raise CapacityAdmissionError("one-node-loss CPU capacity must be below total capacity")
    if numeric_baseline["one_node_loss_allocatable_memory_bytes"] >= numeric_baseline["allocatable_memory_bytes"]:
        raise CapacityAdmissionError("one-node-loss memory capacity must be below total capacity")

    storage_classes = _storage_classes(contract, contract_path)
    components = _mapping(contract.get("components"), "components")
    if set(components) != REQUIRED_COMPONENTS:
        raise CapacityAdmissionError("capacity contract must contain the exact mandatory Phase 6 component set")
    chart_components = REQUIRED_COMPONENTS - {"environment_foundations", "platform_demo"}
    chart_locks = _mapping(
        _load_one(ROOT / "versions.lock.yaml", "versions lock").get("helm_charts"),
        "Helm chart locks",
    )

    aggregate_steady = ZERO_RESOURCES
    aggregate_peak = ZERO_RESOURCES
    document_count = 0
    workload_count = 0
    pvc_count = 0
    logical_pvc_bytes = 0
    raw_pvc_bytes = 0
    loss_pvc_bytes = 0
    identities: set[tuple[str, str, str, str]] = set()
    unrequested_container_count = 0
    component_projection: dict[str, dict[str, int]] = {}
    base = contract_path.resolve().parent
    for component in sorted(REQUIRED_COMPONENTS):
        item = _mapping(components[component], f"component {component}")
        if component in chart_components:
            chart_lock = _mapping(chart_locks.get(component), f"chart lock {component}")
            if item.get("chart_archive_sha256") != chart_lock.get("archive_sha256"):
                raise CapacityAdmissionError(f"component {component} chart checksum differs from versions.lock.yaml")
        elif "chart_archive_sha256" in item:
            raise CapacityAdmissionError(f"component {component} unexpectedly claims an external chart")
        source_inputs = _list(item.get("source_inputs"), f"component {component} source inputs")
        if not source_inputs:
            raise CapacityAdmissionError(f"component {component} has no checksum-bound source inputs")
        for source_index, source_item in enumerate(source_inputs):
            source = _mapping(source_item, f"component {component} source input {source_index}")
            source_path_value = source.get("path")
            source_sha256 = source.get("sha256")
            recursive = source.get("recursive")
            if not isinstance(source_path_value, str) or not source_path_value or Path(source_path_value).is_absolute():
                raise CapacityAdmissionError(f"component {component} has an invalid source path")
            source_path = (ROOT / source_path_value).resolve()
            try:
                source_path.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise CapacityAdmissionError(f"component {component} source escapes the repository") from exc
            if not isinstance(source_sha256, str) or not SHA256.fullmatch(source_sha256):
                raise CapacityAdmissionError(f"component {component} has an invalid source checksum")
            if not isinstance(recursive, bool):
                raise CapacityAdmissionError(f"component {component} source recursion flag is invalid")
            if recursive:
                if source_path.is_symlink() or not source_path.is_dir():
                    raise CapacityAdmissionError(f"component {component} recursive source is not a directory")
                files = [path for path in sorted(source_path.rglob("*")) if path.is_file()]
                if not files or any(path.is_symlink() for path in files):
                    raise CapacityAdmissionError(f"component {component} recursive source is unsafe")
                digest = hashlib.sha256()
                for path in files:
                    digest.update(path.relative_to(source_path).as_posix().encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(hashlib.sha256(_read_regular(path, f"component {component} source")).digest())
                    digest.update(b"\0")
                actual_source_sha256 = digest.hexdigest()
            else:
                actual_source_sha256 = hashlib.sha256(_read_regular(source_path, f"component {component} source")).hexdigest()
            if actual_source_sha256 != source_sha256:
                raise CapacityAdmissionError(f"component {component} source checksum changed")
        render_path_value = item.get("render_path")
        render_sha256 = item.get("render_sha256")
        if not isinstance(render_path_value, str) or not render_path_value:
            raise CapacityAdmissionError(f"component {component} has no render_path")
        if not isinstance(render_sha256, str) or not SHA256.fullmatch(render_sha256):
            raise CapacityAdmissionError(f"component {component} has no exact render_sha256")
        render_path = Path(render_path_value)
        if not render_path.is_absolute():
            render_path = (base / render_path).resolve()
        documents = _load_render(render_path, render_sha256, f"component {component} render")
        for document in documents:
            if document.get("kind") not in STANDARD_WORKLOAD_KINDS:
                continue
            specification = _mapping(document.get("spec"), f"component {component} workload spec")
            pod_specification = specification if document.get("kind") == "Pod" else _mapping(
                _mapping(specification.get("template"), f"component {component} workload template").get("spec"),
                f"component {component} pod spec",
            )
            for container in pod_specification.get("initContainers", []) + pod_specification.get("containers", []):
                resources = container.get("resources") if isinstance(container, dict) else None
                requests = resources.get("requests") if isinstance(resources, dict) else None
                if not isinstance(requests, dict) or "cpu" not in requests or "memory" not in requests:
                    unrequested_container_count += 1
        capacity = component_capacity(
            documents,
            item,
            node_count,
            storage_classes,
            component,
            identities,
            projection_only,
            candidate_nodes,
        )
        document_count += capacity.document_count
        workload_count += capacity.workload_count
        pvc_count += capacity.pvc_definition_count
        aggregate_steady = aggregate_steady.plus(capacity.steady)
        aggregate_peak = aggregate_peak.plus(capacity.peak)
        logical_pvc_bytes += capacity.logical_pvc_bytes
        raw_pvc_bytes += capacity.raw_pvc_bytes
        loss_pvc_bytes += capacity.one_node_loss_pvc_bytes
        component_projection[component] = {
            "steady_cpu_millicores": capacity.steady.request_cpu_millicores,
            "rollout_peak_cpu_millicores": capacity.peak.request_cpu_millicores,
            "steady_memory_bytes": capacity.steady.request_memory_bytes,
            "rollout_peak_memory_bytes": capacity.peak.request_memory_bytes,
            "logical_pvc_bytes": capacity.logical_pvc_bytes,
            "raw_pvc_bytes": capacity.raw_pvc_bytes,
            "one_node_loss_pvc_bytes": capacity.one_node_loss_pvc_bytes,
        }

    post_steady_cpu = numeric_baseline["existing_requested_cpu_millicores"] + aggregate_steady.request_cpu_millicores
    post_steady_memory = numeric_baseline["existing_requested_memory_bytes"] + aggregate_steady.request_memory_bytes
    post_peak_cpu = numeric_baseline["existing_requested_cpu_millicores"] + aggregate_peak.request_cpu_millicores
    post_peak_memory = numeric_baseline["existing_requested_memory_bytes"] + aggregate_peak.request_memory_bytes
    cpu_headroom = numeric_baseline["one_node_loss_allocatable_cpu_millicores"] - post_peak_cpu
    memory_headroom = numeric_baseline["one_node_loss_allocatable_memory_bytes"] - post_peak_memory
    storage_headroom = numeric_baseline["storage_available_bytes"] - raw_pvc_bytes
    loss_storage_headroom = numeric_baseline["worst_two_node_storage_available_bytes"] - loss_pvc_bytes

    tracked_projection = contract.get("projection_result")
    expected_projection = _mapping(tracked_projection, "projection_result")
    candidate_cpu = sum(node.cpu_millicores for node in candidate_nodes)
    candidate_memory = sum(node.memory_bytes for node in candidate_nodes)
    candidate_loss_cpu = sum(sorted(node.cpu_millicores for node in candidate_nodes)[:2])
    candidate_loss_memory = sum(sorted(node.memory_bytes for node in candidate_nodes)[:2])
    candidate_storage = sum(node.storage_available_bytes for node in candidate_nodes)
    candidate_loss_storage = sum(sorted(node.storage_available_bytes for node in candidate_nodes)[:2])
    candidate_cpu_headroom = candidate_loss_cpu - post_peak_cpu
    candidate_memory_headroom = candidate_loss_memory - post_peak_memory
    candidate_storage_headroom = candidate_storage - raw_pvc_bytes
    candidate_loss_storage_headroom = candidate_loss_storage - loss_pvc_bytes
    exact_projection = {
        "candidate_allocatable_cpu_millicores": candidate_cpu,
        "candidate_allocatable_memory_bytes": candidate_memory,
        "candidate_one_node_loss_allocatable_cpu_millicores": candidate_loss_cpu,
        "candidate_one_node_loss_allocatable_memory_bytes": candidate_loss_memory,
        "candidate_storage_available_bytes": candidate_storage,
        "candidate_one_node_loss_storage_available_bytes": candidate_loss_storage,
        "candidate_one_node_loss_cpu_headroom_millicores": candidate_cpu_headroom,
        "candidate_one_node_loss_cpu_reserve_shortfall_millicores": max(0, numeric_baseline["required_cpu_reserve_millicores"] - candidate_cpu_headroom),
        "candidate_one_node_loss_memory_headroom_bytes": candidate_memory_headroom,
        "candidate_one_node_loss_memory_reserve_headroom_bytes": candidate_memory_headroom - numeric_baseline["required_memory_reserve_bytes"],
        "candidate_storage_headroom_bytes": candidate_storage_headroom,
        "candidate_one_node_loss_storage_headroom_bytes": candidate_loss_storage_headroom,
        "rendered_document_count": document_count,
        "workload_definition_count": workload_count,
        "pvc_definition_count": pvc_count,
        "unrequested_container_count": unrequested_container_count,
        "new_steady_cpu_millicores": aggregate_steady.request_cpu_millicores,
        "new_rollout_peak_cpu_millicores": aggregate_peak.request_cpu_millicores,
        "new_steady_memory_bytes": aggregate_steady.request_memory_bytes,
        "new_rollout_peak_memory_bytes": aggregate_peak.request_memory_bytes,
        "new_logical_pvc_bytes": logical_pvc_bytes,
        "new_raw_pvc_bytes": raw_pvc_bytes,
        "one_node_loss_pvc_bytes": loss_pvc_bytes,
        "post_steady_cpu_millicores": post_steady_cpu,
        "post_rollout_peak_cpu_millicores": post_peak_cpu,
        "post_steady_memory_bytes": post_steady_memory,
        "post_rollout_peak_memory_bytes": post_peak_memory,
        "total_cpu_shortfall_millicores": max(0, post_steady_cpu - numeric_baseline["allocatable_cpu_millicores"]),
        "one_node_loss_cpu_headroom_millicores": cpu_headroom,
        "one_node_loss_cpu_reserve_shortfall_millicores": max(0, numeric_baseline["required_cpu_reserve_millicores"] - cpu_headroom),
        "one_node_loss_memory_headroom_bytes": memory_headroom,
        "one_node_loss_memory_reserve_headroom_bytes": memory_headroom - numeric_baseline["required_memory_reserve_bytes"],
        "required_candidate_two_node_cpu_millicores": post_peak_cpu + numeric_baseline["required_cpu_reserve_millicores"],
        "required_candidate_per_node_cpu_millicores": math.ceil((post_peak_cpu + numeric_baseline["required_cpu_reserve_millicores"]) / 2),
        "required_candidate_two_node_memory_bytes": post_peak_memory + numeric_baseline["required_memory_reserve_bytes"],
        "required_candidate_per_node_memory_bytes": math.ceil((post_peak_memory + numeric_baseline["required_memory_reserve_bytes"]) / 2),
        "storage_headroom_bytes": storage_headroom,
        "one_node_loss_storage_headroom_bytes": loss_storage_headroom,
    }
    if projection_only:
        for key in tuple(exact_projection):
            if key.startswith("candidate_"):
                exact_projection[key] = None
    if set(expected_projection) != set(exact_projection) or expected_projection != exact_projection:
        raise CapacityAdmissionError("tracked projection_result does not exactly match recomputed protected inputs and renders")

    if unrequested_container_count and not projection_only:
        raise CapacityAdmissionError("rendered workloads contain containers without explicit CPU and memory requests")

    if not projection_only and (post_steady_cpu > candidate_cpu or post_steady_memory > candidate_memory):
        raise CapacityAdmissionError("steady-state Phase 6 requests exceed candidate cluster capacity")
    if not projection_only and candidate_cpu_headroom < numeric_baseline["required_cpu_reserve_millicores"]:
        raise CapacityAdmissionError("rollout peak violates candidate one-node-loss CPU reserve")
    if not projection_only and candidate_memory_headroom < numeric_baseline["required_memory_reserve_bytes"]:
        raise CapacityAdmissionError("rollout peak violates candidate one-node-loss memory reserve")
    if not projection_only and candidate_storage_headroom < numeric_baseline["required_storage_reserve_bytes"]:
        raise CapacityAdmissionError("PVC replicas violate candidate total storage reserve")
    if not projection_only and candidate_loss_storage_headroom < numeric_baseline["required_storage_reserve_bytes"]:
        raise CapacityAdmissionError("PVC replicas violate candidate one-node-loss storage reserve")

    reported_cpu_headroom = cpu_headroom if projection_only else candidate_cpu_headroom
    reported_memory_headroom = memory_headroom if projection_only else candidate_memory_headroom
    reported_storage_headroom = storage_headroom if projection_only else candidate_storage_headroom
    reported_loss_storage_headroom = loss_storage_headroom if projection_only else candidate_loss_storage_headroom
    return {
        "schema_version": 1,
        "status": "PASS",
        "component_count": len(REQUIRED_COMPONENTS),
        "rendered_document_count": document_count,
        "workload_definition_count": workload_count,
        "pvc_definition_count": pvc_count,
        "new_steady_cpu_millicores": aggregate_steady.request_cpu_millicores,
        "new_rollout_peak_cpu_millicores": aggregate_peak.request_cpu_millicores,
        "capacity_source": "baseline-projection" if projection_only else "protected-candidate-evidence",
        "one_node_loss_rollout_cpu_headroom_millicores": reported_cpu_headroom,
        "new_steady_memory_bytes": aggregate_steady.request_memory_bytes,
        "new_rollout_peak_memory_bytes": aggregate_peak.request_memory_bytes,
        "one_node_loss_rollout_memory_headroom_bytes": reported_memory_headroom,
        "new_logical_pvc_bytes": logical_pvc_bytes,
        "new_raw_pvc_bytes": raw_pvc_bytes,
        "one_node_loss_pvc_bytes": loss_pvc_bytes,
        "storage_headroom_bytes": reported_storage_headroom,
        "one_node_loss_storage_headroom_bytes": reported_loss_storage_headroom,
        "unrequested_container_count": unrequested_container_count,
        "component_projection": component_projection,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--projection-only",
        action="store_true",
        help="verify renders and report component totals without claiming cluster admission",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = args.contract.resolve()
    try:
        contract = _load_one(contract_path, "capacity contract")
        if args.projection_only:
            projected = deepcopy(contract)
            projected["_projection_only"] = True
            projected["admission_status"] = "ready"
            full = evaluate(projected, contract_path)
            report = {
                key: value
                for key, value in full.items()
                if key.startswith("new_")
                or key in {"schema_version", "component_count", "rendered_document_count", "workload_definition_count", "pvc_definition_count", "unrequested_container_count", "one_node_loss_pvc_bytes", "component_projection"}
            }
            report["status"] = "PROJECTED"
        else:
            report = evaluate(contract, contract_path)
    except (CapacityAdmissionError, OSError) as exc:
        print(f"[FAIL] Phase 6 capacity admission: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
