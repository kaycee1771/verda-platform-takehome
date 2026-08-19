#!/usr/bin/env python3
"""Validate raw Longhorn test captures and emit identity-free scalar evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

EXPECTED_NODES = {f"verda-mgmt-server-{index:02d}" for index in range(1, 4)}
EXPECTED_STORAGE_CLASS = "longhorn-critical"
EXPECTED_CHECKSUM = "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8"
EXPECTED_IMAGE = (
    "quay.io/cilium/alpine-curl:v1.10.0@sha256:"
    "913e8c9f3d960dde03882defa0edd3a919d529c2eb167caa7f54194528bde364"
)
RUN_ID = re.compile(r"^p5st-[0-9]{8}t[0-9]{6}z-[a-f0-9]{8}$")
MAX_INPUT_BYTES = 32 * 1024**2


class ContractError(ValueError):
    """Raised when a live capture violates the storage-test contract."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("JSON contains a duplicate object key")
        result[key] = value
    return result


def load_json(path: Path, label: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} must be a regular, non-symlink file")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ContractError(f"{label} exceeds the bounded input size")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ContractError("JSON contains a non-finite number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid UTF-8 JSON") from exc


def mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def items(document: Any, label: str) -> list[dict[str, Any]]:
    rows = mapping(document, label).get("items")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ContractError(f"{label} must contain an items array")
    return rows


def ready_pod(pod: dict[str, Any]) -> bool:
    conditions = {
        condition.get("type"): condition.get("status")
        for condition in pod.get("status", {}).get("conditions", [])
    }
    return (
        pod.get("status", {}).get("phase") == "Running"
        and conditions.get("Ready") == "True"
    )


def exact_item(rows: list[dict[str, Any]], name: str, label: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get("metadata", {}).get("name") == name]
    if len(matches) != 1:
        raise ContractError(f"{label} identity is absent or ambiguous")
    return matches[0]


def validate_run_id(run_id: str) -> None:
    if not RUN_ID.fullmatch(run_id):
        raise ContractError("run ID does not satisfy the bounded identity format")


def validate_storage_class(document: Any) -> dict[str, Any]:
    storage_class = mapping(document, "StorageClass")
    if (
        storage_class.get("apiVersion") != "storage.k8s.io/v1"
        or storage_class.get("kind") != "StorageClass"
    ):
        raise ContractError("longhorn-critical is not a v1 StorageClass")
    if storage_class.get("metadata", {}).get("name") != EXPECTED_STORAGE_CLASS:
        raise ContractError("unexpected critical StorageClass identity")
    if storage_class.get("provisioner") != "driver.longhorn.io":
        raise ContractError(
            "critical StorageClass does not use the Longhorn CSI driver"
        )
    if storage_class.get("parameters", {}).get("numberOfReplicas") != "3":
        raise ContractError("critical StorageClass does not require three replicas")
    if storage_class.get("reclaimPolicy") != "Retain":
        raise ContractError(
            "critical StorageClass must retain protected data by default"
        )
    if storage_class.get("volumeBindingMode") != "WaitForFirstConsumer":
        raise ContractError("critical StorageClass must wait for a workload consumer")
    if storage_class.get("allowVolumeExpansion") is not True:
        raise ContractError("critical StorageClass must permit controlled expansion")
    return {
        "storage_class_contract": True,
        "storage_class_replicas": 3,
    }


def capture_identity(
    pvc_document: Any,
    pv_document: Any,
    volumes_document: Any,
    pod_document: Any,
    run_id: str,
    namespace: str,
) -> dict[str, Any]:
    validate_run_id(run_id)
    pvc = mapping(pvc_document, "PVC")
    metadata = pvc.get("metadata", {})
    if (
        metadata.get("name") != "checksum-data"
        or metadata.get("namespace") != namespace
    ):
        raise ContractError("bounded PVC identity changed")
    labels = metadata.get("labels", {})
    if (
        labels.get("platform.verda-demo.io/test") != "longhorn-reschedule"
        or labels.get("platform.verda-demo.io/run-id") != run_id
    ):
        raise ContractError("bounded PVC ownership labels changed")
    if pvc.get("status", {}).get("phase") != "Bound":
        raise ContractError("bounded PVC is not Bound")
    if pvc.get("spec", {}).get("storageClassName") != EXPECTED_STORAGE_CLASS:
        raise ContractError("bounded PVC does not use longhorn-critical")
    pvc_uid = metadata.get("uid")
    pv_name = pvc.get("spec", {}).get("volumeName")
    if (
        not isinstance(pvc_uid, str)
        or not pvc_uid
        or not isinstance(pv_name, str)
        or not pv_name
    ):
        raise ContractError("bounded PVC lacks immutable identity")

    pv = exact_item(items(pv_document, "PersistentVolumeList"), pv_name, "bound PV")
    pv_uid = pv.get("metadata", {}).get("uid")
    pv_spec = pv.get("spec", {})
    csi = pv_spec.get("csi", {})
    volume_handle = csi.get("volumeHandle")
    if (
        not isinstance(pv_uid, str)
        or not pv_uid
        or csi.get("driver") != "driver.longhorn.io"
        or not isinstance(volume_handle, str)
        or not volume_handle
        or pv_spec.get("storageClassName") != EXPECTED_STORAGE_CLASS
        or pv_spec.get("persistentVolumeReclaimPolicy") != "Retain"
    ):
        raise ContractError("bound PV does not satisfy the Longhorn identity contract")

    volume = exact_item(
        items(volumes_document, "Longhorn VolumeList"), volume_handle, "Longhorn volume"
    )
    volume_uid = volume.get("metadata", {}).get("uid")
    if not isinstance(volume_uid, str) or not volume_uid:
        raise ContractError("Longhorn volume lacks immutable identity")
    if volume.get("spec", {}).get("numberOfReplicas") != 3:
        raise ContractError("Longhorn volume does not request three replicas")

    pod = mapping(pod_document, "writer pod")
    node = pod.get("spec", {}).get("nodeName")
    image = pod.get("spec", {}).get("containers", [{}])[0].get("image")
    if node not in EXPECTED_NODES or not ready_pod(pod) or image != EXPECTED_IMAGE:
        raise ContractError("writer pod identity, readiness, or image contract failed")

    return {
        "schema_version": 1,
        "run_id": run_id,
        "namespace": namespace,
        "pvc_uid": pvc_uid,
        "pv_name": pv_name,
        "pv_uid": pv_uid,
        "volume_handle": volume_handle,
        "volume_uid": volume_uid,
        "source_node": node,
    }


def validate_health(
    identity: dict[str, Any], volumes_document: Any, replicas_document: Any
) -> dict[str, Any]:
    handle = identity.get("volume_handle")
    volume = exact_item(
        items(volumes_document, "Longhorn VolumeList"), handle, "Longhorn volume"
    )
    if volume.get("metadata", {}).get("uid") != identity.get("volume_uid"):
        raise ContractError("Longhorn volume identity changed")
    spec = volume.get("spec", {})
    status = volume.get("status", {})
    if (
        spec.get("numberOfReplicas") != 3
        or status.get("state") != "attached"
        or status.get("robustness") != "healthy"
    ):
        raise ContractError(
            "Longhorn volume is not attached and healthy with three replicas"
        )

    replicas = [
        replica
        for replica in items(replicas_document, "Longhorn ReplicaList")
        if replica.get("spec", {}).get("volumeName") == handle
    ]
    if len(replicas) != 3:
        raise ContractError(
            "Longhorn volume does not have exactly three replica objects"
        )
    replica_nodes: set[str] = set()
    for replica in replicas:
        replica_spec = replica.get("spec", {})
        if (
            replica_spec.get("nodeID") not in EXPECTED_NODES
            or replica_spec.get("failedAt", "") != ""
            or not replica_spec.get("healthyAt")
            or replica.get("status", {}).get("currentState") != "running"
        ):
            raise ContractError(
                "a Longhorn replica is failed, rebuilding, or not running"
            )
        replica_nodes.add(replica_spec["nodeID"])
    if replica_nodes != EXPECTED_NODES:
        raise ContractError("Longhorn replicas are not spread across all three nodes")
    return {
        "healthy_replicas": 3,
        "replicas_on_distinct_nodes": True,
        "volume_attached": True,
        "volume_healthy": True,
    }


def verify_reschedule(
    identity: dict[str, Any],
    pvc_document: Any,
    pv_document: Any,
    volumes_document: Any,
    pod_document: Any,
) -> dict[str, Any]:
    pvc = mapping(pvc_document, "PVC")
    if (
        pvc.get("metadata", {}).get("uid") != identity.get("pvc_uid")
        or pvc.get("spec", {}).get("volumeName") != identity.get("pv_name")
        or pvc.get("status", {}).get("phase") != "Bound"
    ):
        raise ContractError("PVC identity was not preserved during rescheduling")
    pv = exact_item(
        items(pv_document, "PersistentVolumeList"), identity.get("pv_name"), "bound PV"
    )
    if pv.get("metadata", {}).get("uid") != identity.get("pv_uid") or pv.get(
        "spec", {}
    ).get("csi", {}).get("volumeHandle") != identity.get("volume_handle"):
        raise ContractError("PV identity was not preserved during rescheduling")
    volume = exact_item(
        items(volumes_document, "Longhorn VolumeList"),
        identity.get("volume_handle"),
        "Longhorn volume",
    )
    if volume.get("metadata", {}).get("uid") != identity.get("volume_uid"):
        raise ContractError(
            "Longhorn data identity was not preserved during rescheduling"
        )
    pod = mapping(pod_document, "reader pod")
    target_node = pod.get("spec", {}).get("nodeName")
    if target_node not in EXPECTED_NODES or target_node == identity.get("source_node"):
        raise ContractError(
            "reader pod was not rescheduled to a different management node"
        )
    if not ready_pod(pod):
        raise ContractError("reader pod is not Running and Ready")
    return {
        "checksum_verified_after_reschedule": True,
        "pvc_identity_preserved": True,
        "pv_identity_preserved": True,
        "rescheduled_to_different_node": True,
        "volume_identity_preserved": True,
    }


def validate_namespace(document: Any, run_id: str, namespace: str) -> dict[str, Any]:
    validate_run_id(run_id)
    item = mapping(document, "test namespace")
    metadata = item.get("metadata", {})
    labels = metadata.get("labels", {})
    if metadata.get("name") != namespace:
        raise ContractError("cleanup namespace identity changed")
    if (
        labels.get("platform.verda-demo.io/test") != "longhorn-reschedule"
        or labels.get("platform.verda-demo.io/run-id") != run_id
    ):
        raise ContractError("cleanup ownership labels do not match the exact run")
    return {"cleanup_ownership_validated": True}


def validate_cleanup_target(
    identity: dict[str, Any],
    namespace_document: Any,
    pvc_document: Any,
    pv_document: Any,
    volumes_document: Any,
    run_id: str,
    namespace: str,
    expected_reclaim_policy: str,
) -> dict[str, Any]:
    """Prove the exact test-owned PV boundary before and after lifecycle patching."""

    if expected_reclaim_policy not in {"Retain", "Delete"}:
        raise ContractError("unsupported cleanup reclaim-policy assertion")
    validate_namespace(namespace_document, run_id, namespace)
    if identity.get("run_id") != run_id or identity.get("namespace") != namespace:
        raise ContractError("cleanup identity is not owned by the exact test run")

    pvc = mapping(pvc_document, "cleanup PVC")
    pvc_metadata = pvc.get("metadata", {})
    pvc_spec = pvc.get("spec", {})
    pvc_labels = pvc_metadata.get("labels", {})
    if (
        pvc_metadata.get("name") != "checksum-data"
        or pvc_metadata.get("namespace") != namespace
        or pvc_metadata.get("uid") != identity.get("pvc_uid")
        or pvc_labels.get("platform.verda-demo.io/test") != "longhorn-reschedule"
        or pvc_labels.get("platform.verda-demo.io/run-id") != run_id
        or pvc_spec.get("storageClassName") != EXPECTED_STORAGE_CLASS
        or pvc_spec.get("volumeName") != identity.get("pv_name")
        or pvc.get("status", {}).get("phase") != "Bound"
    ):
        raise ContractError("cleanup PVC ownership or immutable identity changed")

    pv = exact_item(
        items(pv_document, "cleanup PersistentVolumeList"),
        identity.get("pv_name"),
        "cleanup PV",
    )
    pv_metadata = pv.get("metadata", {})
    pv_spec = pv.get("spec", {})
    claim_ref = pv_spec.get("claimRef", {})
    csi = pv_spec.get("csi", {})
    if (
        pv_metadata.get("uid") != identity.get("pv_uid")
        or pv_spec.get("storageClassName") != EXPECTED_STORAGE_CLASS
        or pv_spec.get("persistentVolumeReclaimPolicy") != expected_reclaim_policy
        or claim_ref.get("namespace") != namespace
        or claim_ref.get("name") != "checksum-data"
        or claim_ref.get("uid") != identity.get("pvc_uid")
        or csi.get("driver") != "driver.longhorn.io"
        or csi.get("volumeHandle") != identity.get("volume_handle")
    ):
        raise ContractError(
            "cleanup PV ownership, policy, or immutable identity changed"
        )

    volume = exact_item(
        items(volumes_document, "cleanup Longhorn VolumeList"),
        identity.get("volume_handle"),
        "cleanup Longhorn volume",
    )
    kubernetes_status = volume.get("status", {}).get("kubernetesStatus", {})
    if (
        volume.get("metadata", {}).get("uid") != identity.get("volume_uid")
        or volume.get("spec", {}).get("numberOfReplicas") != 3
        or kubernetes_status.get("namespace") != namespace
        or kubernetes_status.get("pvcName") != "checksum-data"
        or kubernetes_status.get("pvName") != identity.get("pv_name")
    ):
        raise ContractError("cleanup Longhorn volume ownership or identity changed")

    return {
        "cleanup_target_validated": True,
        "cleanup_reclaim_policy": expected_reclaim_policy,
    }


def validate_absence(
    identity: dict[str, Any],
    namespace: str,
    namespace_document: Any,
    pv_document: Any,
    volumes_document: Any,
) -> dict[str, Any]:
    if any(
        item.get("metadata", {}).get("name") == namespace
        for item in items(namespace_document, "NamespaceList")
    ):
        raise ContractError("bounded test namespace remains after cleanup")
    for pv in items(pv_document, "PersistentVolumeList"):
        if pv.get("metadata", {}).get("name") == identity.get("pv_name") or pv.get(
            "metadata", {}
        ).get("uid") == identity.get("pv_uid"):
            raise ContractError("bounded test PV remains after cleanup")
    for volume in items(volumes_document, "Longhorn VolumeList"):
        if volume.get("metadata", {}).get("name") == identity.get(
            "volume_handle"
        ) or volume.get("metadata", {}).get("uid") == identity.get("volume_uid"):
            raise ContractError("bounded Longhorn volume remains after cleanup")
    return {
        "cleanup_absence_proven": True,
        "longhorn_test_data_removed_only_at_cleanup": True,
    }


def validate_run_absence(
    run_id: str,
    namespace: str,
    namespace_document: Any,
    pv_document: Any,
    volumes_document: Any,
) -> dict[str, Any]:
    validate_run_id(run_id)
    if namespace != f"longhorn-test-{run_id}":
        raise ContractError("run-scoped cleanup namespace identity changed")
    if any(
        item.get("metadata", {}).get("name") == namespace
        for item in items(namespace_document, "NamespaceList")
    ):
        raise ContractError("bounded test namespace remains after cleanup")
    for pv in items(pv_document, "PersistentVolumeList"):
        if pv.get("spec", {}).get("claimRef", {}).get("namespace") == namespace:
            raise ContractError("a PV still references the bounded test namespace")
    for volume in items(volumes_document, "Longhorn VolumeList"):
        kubernetes_status = volume.get("status", {}).get("kubernetesStatus", {})
        if kubernetes_status.get("namespace") == namespace:
            raise ContractError(
                "a Longhorn volume still references the bounded test namespace"
            )
    return {"run_scoped_storage_absence_proven": True}


def selected_capacity(prefix: str, document: Any) -> dict[str, Any]:
    data = mapping(document, f"{prefix} capacity")
    required = (
        "scheduled_active_pods",
        "requested_cpu_cores",
        "requested_memory_gib",
        "one_node_loss_cpu_headroom_cores",
        "one_node_loss_memory_headroom_gib",
    )
    result: dict[str, Any] = {}
    for key in required:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError(f"{prefix} capacity scalar is absent or invalid")
        result[f"{prefix}_{key}"] = value
    return result


def selected_longhorn_capacity(prefix: str, document: Any) -> dict[str, Any]:
    data = mapping(document, f"{prefix} Longhorn capacity")
    required = (
        "longhorn_schedulable_node_count",
        "longhorn_dedicated_disk_count",
        "total_storage_available_bytes",
        "total_storage_scheduled_bytes",
        "worst_case_two_node_available_bytes",
    )
    result: dict[str, Any] = {}
    for key in required:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(
                f"{prefix} Longhorn capacity scalar is absent or invalid"
            )
        result[f"{prefix}_{key}"] = value
    return result


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    health_before = mapping(
        load_json(args.health_before, "health-before"), "health-before"
    )
    health_after = mapping(load_json(args.health_after, "health-after"), "health-after")
    reschedule = mapping(load_json(args.reschedule, "reschedule"), "reschedule")
    absence = mapping(load_json(args.absence, "absence"), "absence")
    expected_true = {
        **health_before,
        **health_after,
        **reschedule,
        **absence,
    }
    for key, value in expected_true.items():
        if key == "healthy_replicas":
            if value != 3:
                raise ContractError("health evidence does not prove three replicas")
        elif value is not True:
            raise ContractError("storage evidence contains a failed boolean gate")

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "payload_bytes": 4 * 1024**2,
        "payload_sha256": EXPECTED_CHECKSUM,
        "healthy_replicas_before": health_before["healthy_replicas"],
        "healthy_replicas_after": health_after["healthy_replicas"],
        **reschedule,
        **absence,
    }
    report.update(
        selected_capacity("pre", load_json(args.capacity_pre, "capacity-pre"))
    )
    report.update(
        selected_capacity("post", load_json(args.capacity_post, "capacity-post"))
    )
    report.update(
        selected_longhorn_capacity(
            "pre", load_json(args.longhorn_capacity_pre, "Longhorn-capacity-pre")
        )
    )
    report.update(
        selected_longhorn_capacity(
            "post", load_json(args.longhorn_capacity_post, "Longhorn-capacity-post")
        )
    )
    report["run_id_sha256"] = hashlib.sha256(args.run_id.encode()).hexdigest()
    return report


def write_private_json(path: Path, document: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def print_json(document: dict[str, Any]) -> None:
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    storage_class = subparsers.add_parser("storage-class")
    storage_class.add_argument("--input", required=True, type=Path)

    identity = subparsers.add_parser("capture-identity")
    for name in ("pvc", "pvs", "volumes", "pod"):
        identity.add_argument(f"--{name}", required=True, type=Path)
    identity.add_argument("--run-id", required=True)
    identity.add_argument("--namespace", required=True)
    identity.add_argument("--output", required=True, type=Path)

    health = subparsers.add_parser("health")
    health.add_argument("--identity", required=True, type=Path)
    health.add_argument("--volumes", required=True, type=Path)
    health.add_argument("--replicas", required=True, type=Path)

    reschedule = subparsers.add_parser("reschedule")
    reschedule.add_argument("--identity", required=True, type=Path)
    for name in ("pvc", "pvs", "volumes", "pod"):
        reschedule.add_argument(f"--{name}", required=True, type=Path)

    namespace = subparsers.add_parser("namespace")
    namespace.add_argument("--input", required=True, type=Path)
    namespace.add_argument("--run-id", required=True)
    namespace.add_argument("--namespace", required=True)

    cleanup_target = subparsers.add_parser("cleanup-target")
    cleanup_target.add_argument("--identity", required=True, type=Path)
    cleanup_target.add_argument("--namespace-file", required=True, type=Path)
    cleanup_target.add_argument("--pvc", required=True, type=Path)
    cleanup_target.add_argument("--pvs", required=True, type=Path)
    cleanup_target.add_argument("--volumes", required=True, type=Path)
    cleanup_target.add_argument("--run-id", required=True)
    cleanup_target.add_argument("--namespace", required=True)
    cleanup_target.add_argument(
        "--expected-reclaim-policy", choices=("Retain", "Delete"), required=True
    )

    absence = subparsers.add_parser("absence")
    absence.add_argument("--identity", required=True, type=Path)
    absence.add_argument("--namespace", required=True)
    absence.add_argument("--namespaces", required=True, type=Path)
    absence.add_argument("--pvs", required=True, type=Path)
    absence.add_argument("--volumes", required=True, type=Path)

    run_absence = subparsers.add_parser("run-absence")
    run_absence.add_argument("--run-id", required=True)
    run_absence.add_argument("--namespace", required=True)
    run_absence.add_argument("--namespaces", required=True, type=Path)
    run_absence.add_argument("--pvs", required=True, type=Path)
    run_absence.add_argument("--volumes", required=True, type=Path)

    report = subparsers.add_parser("report")
    for name in (
        "capacity-pre",
        "capacity-post",
        "longhorn-capacity-pre",
        "longhorn-capacity-post",
        "health-before",
        "health-after",
        "reschedule",
        "absence",
    ):
        report.add_argument(f"--{name}", required=True, type=Path)
    report.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "storage-class":
            print_json(validate_storage_class(load_json(args.input, "StorageClass")))
        elif args.command == "capture-identity":
            identity = capture_identity(
                load_json(args.pvc, "PVC"),
                load_json(args.pvs, "PersistentVolumeList"),
                load_json(args.volumes, "Longhorn VolumeList"),
                load_json(args.pod, "writer pod"),
                args.run_id,
                args.namespace,
            )
            write_private_json(args.output, identity)
        elif args.command == "health":
            print_json(
                validate_health(
                    mapping(load_json(args.identity, "identity"), "identity"),
                    load_json(args.volumes, "Longhorn VolumeList"),
                    load_json(args.replicas, "Longhorn ReplicaList"),
                )
            )
        elif args.command == "reschedule":
            print_json(
                verify_reschedule(
                    mapping(load_json(args.identity, "identity"), "identity"),
                    load_json(args.pvc, "PVC"),
                    load_json(args.pvs, "PersistentVolumeList"),
                    load_json(args.volumes, "Longhorn VolumeList"),
                    load_json(args.pod, "reader pod"),
                )
            )
        elif args.command == "namespace":
            print_json(
                validate_namespace(
                    load_json(args.input, "test namespace"), args.run_id, args.namespace
                )
            )
        elif args.command == "cleanup-target":
            print_json(
                validate_cleanup_target(
                    mapping(load_json(args.identity, "identity"), "identity"),
                    load_json(args.namespace_file, "test namespace"),
                    load_json(args.pvc, "cleanup PVC"),
                    load_json(args.pvs, "cleanup PersistentVolumeList"),
                    load_json(args.volumes, "cleanup Longhorn VolumeList"),
                    args.run_id,
                    args.namespace,
                    args.expected_reclaim_policy,
                )
            )
        elif args.command == "absence":
            print_json(
                validate_absence(
                    mapping(load_json(args.identity, "identity"), "identity"),
                    args.namespace,
                    load_json(args.namespaces, "NamespaceList"),
                    load_json(args.pvs, "PersistentVolumeList"),
                    load_json(args.volumes, "Longhorn VolumeList"),
                )
            )
        elif args.command == "run-absence":
            print_json(
                validate_run_absence(
                    args.run_id,
                    args.namespace,
                    load_json(args.namespaces, "NamespaceList"),
                    load_json(args.pvs, "PersistentVolumeList"),
                    load_json(args.volumes, "Longhorn VolumeList"),
                )
            )
        elif args.command == "report":
            validate_run_id(args.run_id)
            print_json(build_report(args))
        else:  # pragma: no cover - argparse enforces the command set
            raise ContractError("unsupported command")
    except (ContractError, OSError, KeyError, IndexError) as exc:
        print(f"[FAIL] Longhorn storage-test contract: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
