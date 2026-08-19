#!/usr/bin/env python3
"""Reduce Kubernetes capacity JSON to identity-free Phase 5 scalars."""

from __future__ import annotations

import argparse
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any


CPU_SUFFIXES = {
    "n": Decimal("0.000000001"),
    "u": Decimal("0.000001"),
    "m": Decimal("0.001"),
    "": Decimal(1),
}
BYTE_SUFFIXES = {
    "": Decimal(1),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000**2),
    "G": Decimal(1000**3),
    "T": Decimal(1000**4),
    "P": Decimal(1000**5),
    "E": Decimal(1000**6),
    "Ki": Decimal(1024),
    "Mi": Decimal(1024**2),
    "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4),
    "Pi": Decimal(1024**5),
    "Ei": Decimal(1024**6),
}
QUANTITY = re.compile(r"^([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))([A-Za-z]*)$")


def parse_quantity(value: str | int | float | None, resource: str) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    match = QUANTITY.fullmatch(str(value))
    if not match:
        raise ValueError(f"invalid {resource} quantity")
    number = Decimal(match.group(1))
    suffix = match.group(2)
    factors = CPU_SUFFIXES if resource == "cpu" else BYTE_SUFFIXES
    if suffix not in factors:
        raise ValueError(f"unsupported {resource} quantity suffix")
    result = number * factors[suffix]
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {resource} quantity value")
    return result


def resource_value(resources: dict[str, Any], bucket: str, resource: str) -> Decimal:
    return parse_quantity(resources.get(bucket, {}).get(resource), resource)


def effective_pod_resource(pod: dict[str, Any], bucket: str, resource: str) -> Decimal:
    spec = pod.get("spec", {})
    app_total = sum(
        (resource_value(container.get("resources", {}), bucket, resource)
         for container in spec.get("containers", [])),
        Decimal(0),
    )
    restartable_total = Decimal(0)
    init_peak = Decimal(0)
    for container in spec.get("initContainers", []):
        amount = resource_value(container.get("resources", {}), bucket, resource)
        if container.get("restartPolicy") == "Always":
            restartable_total += amount
            init_peak = max(init_peak, restartable_total)
        else:
            init_peak = max(init_peak, restartable_total + amount)
    steady = app_total + restartable_total
    overhead = parse_quantity(spec.get("overhead", {}).get(resource), resource)
    return max(steady, init_peak) + overhead


def ready_node(node: dict[str, Any]) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in node.get("status", {}).get("conditions", [])
    ) and not node.get("spec", {}).get("unschedulable", False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--pods", required=True, type=Path)
    args = parser.parse_args()

    nodes = json.loads(args.nodes.read_text(encoding="utf-8"))
    pods = json.loads(args.pods.read_text(encoding="utf-8"))
    node_items = nodes.get("items", [])
    pod_items = [
        pod for pod in pods.get("items", [])
        if pod.get("status", {}).get("phase") not in {"Succeeded", "Failed"}
        and pod.get("spec", {}).get("nodeName")
    ]
    if len(node_items) != 3 or sum(ready_node(node) for node in node_items) != 3:
        raise SystemExit("expected exactly three Ready schedulable nodes")

    allocatable_cpu = sum(
        (parse_quantity(node.get("status", {}).get("allocatable", {}).get("cpu"), "cpu")
         for node in node_items),
        Decimal(0),
    )
    allocatable_memory = sum(
        (parse_quantity(node.get("status", {}).get("allocatable", {}).get("memory"), "memory")
         for node in node_items),
        Decimal(0),
    )
    requests_cpu = sum(
        (effective_pod_resource(pod, "requests", "cpu") for pod in pod_items),
        Decimal(0),
    )
    requests_memory = sum(
        (effective_pod_resource(pod, "requests", "memory") for pod in pod_items),
        Decimal(0),
    )
    limits_cpu = sum(
        (effective_pod_resource(pod, "limits", "cpu") for pod in pod_items),
        Decimal(0),
    )
    limits_memory = sum(
        (effective_pod_resource(pod, "limits", "memory") for pod in pod_items),
        Decimal(0),
    )

    result = {
        "nodes": 3,
        "nodes_ready_schedulable": 3,
        "scheduled_active_pods": len(pod_items),
        "allocatable_cpu_cores": float(allocatable_cpu),
        "allocatable_memory_gib": round(float(allocatable_memory / Decimal(1024**3)), 3),
        "requested_cpu_cores": round(float(requests_cpu), 3),
        "requested_memory_gib": round(float(requests_memory / Decimal(1024**3)), 3),
        "limited_cpu_cores": round(float(limits_cpu), 3),
        "limited_memory_gib": round(float(limits_memory / Decimal(1024**3)), 3),
        "request_cpu_percent": round(float(requests_cpu / allocatable_cpu * 100), 2),
        "request_memory_percent": round(float(requests_memory / allocatable_memory * 100), 2),
        "one_node_loss_cpu_headroom_cores": round(
            float((allocatable_cpu * Decimal(2) / Decimal(3)) - requests_cpu), 3
        ),
        "one_node_loss_memory_headroom_gib": round(
            float(((allocatable_memory * Decimal(2) / Decimal(3)) - requests_memory) / Decimal(1024**3)), 3
        ),
    }
    if not all(math.isfinite(value) for value in result.values() if isinstance(value, float)):
        raise SystemExit("non-finite capacity result")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
