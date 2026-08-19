#!/usr/bin/env python3
"""Fail-closed, read-only capacity gate for the Phase 5 Longhorn rollout.

The command consumes sanitized, ignored captures. It never invokes kubectl,
SSH, or a cloud API and emits only aggregate capacity scalars. A pre-install
run requires the Phase 3 mount report. Supplying a Longhorn NodeList adds the
post-install scheduling and one-node-loss headroom checks.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import posixpath
import re
import sys
from collections.abc import Iterable
from typing import Any


EXPECTED_NODES = tuple(f"verda-mgmt-server-{index:02d}" for index in range(1, 4))
EXPECTED_MOUNT = "/var/lib/longhorn"
EXPECTED_DISK = "verda-data"
EXPECTED_NODE_TAG = "management-storage"
EXPECTED_DISK_TAG = "dedicated"
RESERVED_BYTES = 10 * 1024**3
MINIMUM_FILESYSTEM_BYTES = 102005473280
MINIMUM_PREFLIGHT_AVAILABLE_BYTES = 96636764160
MINIMUM_AVAILABLE_PERCENTAGE = 25
MAXIMUM_INPUT_BYTES = 4 * 1024**2
FILESYSTEM_CAPACITY_TOLERANCE_BYTES = 2 * 1024**3
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapacityContractError(ValueError):
    """Raised when an input does not satisfy the capacity contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CapacityContractError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _load_json(path: pathlib.Path, label: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise CapacityContractError(f"{label} must be a regular, non-symlink file")
    if path.stat().st_size > MAXIMUM_INPUT_BYTES:
        raise CapacityContractError(f"{label} exceeds the bounded input size")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(
                CapacityContractError("JSON contains a non-finite number")
            ),
        )
    except UnicodeDecodeError as exc:
        raise CapacityContractError(f"{label} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CapacityContractError(f"{label} is not valid JSON") from exc


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapacityContractError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapacityContractError(f"{label} must be an array")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CapacityContractError(f"{label} must be an integer >= {minimum}")
    return value


def _exact_names(rows: Iterable[dict[str, Any]], field: str, label: str) -> None:
    names = [row.get(field) for row in rows]
    if not all(isinstance(name, str) for name in names):
        raise CapacityContractError(f"{label} contains a non-string node name")
    if len(names) != len(set(names)):
        raise CapacityContractError(f"{label} contains a duplicate node")
    if sorted(names) != list(EXPECTED_NODES):
        raise CapacityContractError(f"{label} must contain exactly the three management nodes")


def _conditions_true(value: Any, label: str) -> None:
    conditions = [_mapping(item, f"{label} condition") for item in _list(value, label)]
    by_type: dict[str, str] = {}
    for condition in conditions:
        condition_type = condition.get("type")
        if not isinstance(condition_type, str) or condition_type in by_type:
            raise CapacityContractError(f"{label} contains an invalid condition type")
        by_type[condition_type] = condition.get("status")
    for required in ("Ready", "Schedulable"):
        if by_type.get(required) != "True":
            raise CapacityContractError(f"{label} requires {required}=True")


def validate_mount_report(report: Any) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    document = _mapping(report, "mount report")
    if document.get("schema_version") != 1 or document.get("raw_uuid_recorded") is not False:
        raise CapacityContractError("mount report provenance or UUID-redaction contract failed")
    rows = [
        _mapping(row, "mount report row")
        for row in _list(document.get("nodes"), "mount report nodes")
    ]
    _exact_names(rows, "node", "mount report")

    capacities: dict[str, dict[str, int]] = {}
    for row in rows:
        node = row["node"]
        if (
            posixpath.normpath(str(row.get("mount", ""))) != EXPECTED_MOUNT
            or row.get("filesystem") != "ext4"
            or row.get("fstab_source") != "UUID"
            or row.get("owner") != "root:root"
            or row.get("mode") != "0750"
            or row.get("status") != "PASS"
            or not SHA256.fullmatch(str(row.get("uuid_sha256", "")))
        ):
            raise CapacityContractError(f"mount contract failed for {node}")
        size = _integer(row.get("size_bytes"), f"{node} filesystem size", MINIMUM_FILESYSTEM_BYTES)
        available = _integer(
            row.get("available_bytes"),
            f"{node} preflight available capacity",
            MINIMUM_PREFLIGHT_AVAILABLE_BYTES,
        )
        if available > size:
            raise CapacityContractError(f"available capacity exceeds filesystem size for {node}")
        capacities[node] = {"size": size, "available": available}

    sizes = [item["size"] for item in capacities.values()]
    available_values = [item["available"] for item in capacities.values()]
    summary = {
        "dedicated_mount_count": len(capacities),
        "total_filesystem_bytes": sum(sizes),
        "minimum_filesystem_bytes": min(sizes),
        "total_preflight_available_bytes": sum(available_values),
        "minimum_preflight_available_bytes": min(available_values),
    }
    return summary, capacities


def validate_longhorn_nodes(
    node_list: Any, mount_capacities: dict[str, dict[str, int]]
) -> dict[str, int]:
    document = _mapping(node_list, "Longhorn NodeList")
    if document.get("apiVersion") != "v1" or document.get("kind") != "List":
        raise CapacityContractError("Longhorn capture must be a Kubernetes v1 List")
    items = [
        _mapping(item, "Longhorn node")
        for item in _list(document.get("items"), "Longhorn nodes")
    ]
    metadata_rows = [_mapping(item.get("metadata"), "Longhorn node metadata") for item in items]
    _exact_names(metadata_rows, "name", "Longhorn NodeList")

    maximum_values: list[int] = []
    available_values: list[int] = []
    scheduled_values: list[int] = []
    for item, metadata in zip(items, metadata_rows, strict=True):
        node = metadata["name"]
        if item.get("apiVersion") != "longhorn.io/v1beta2" or item.get("kind") != "Node":
            raise CapacityContractError(
                f"Longhorn item {node} must be a longhorn.io/v1beta2 Node"
            )
        if metadata.get("namespace") != "longhorn-system":
            raise CapacityContractError(f"Longhorn node {node} is outside longhorn-system")
        spec = _mapping(item.get("spec"), f"{node} spec")
        if (
            spec.get("allowScheduling") is not True
            or spec.get("evictionRequested") is not False
            or _list(spec.get("tags"), f"{node} tags") != [EXPECTED_NODE_TAG]
        ):
            raise CapacityContractError(f"Longhorn node scheduling contract failed for {node}")
        disks = _mapping(spec.get("disks"), f"{node} disks")
        if set(disks) != {EXPECTED_DISK}:
            raise CapacityContractError(
                f"Longhorn node {node} must expose exactly one managed disk"
            )
        disk = _mapping(disks[EXPECTED_DISK], f"{node} disk")
        if (
            disk.get("allowScheduling") is not True
            or disk.get("evictionRequested") is not False
            or disk.get("diskType") != "filesystem"
            or posixpath.normpath(str(disk.get("path", ""))) != EXPECTED_MOUNT
            or _integer(disk.get("storageReserved"), f"{node} reserved capacity") != RESERVED_BYTES
            or _list(disk.get("tags"), f"{node} disk tags") != [EXPECTED_DISK_TAG]
        ):
            raise CapacityContractError(f"Longhorn dedicated-disk contract failed for {node}")

        status = _mapping(item.get("status"), f"{node} status")
        _conditions_true(status.get("conditions"), f"{node} node conditions")
        disk_statuses = _mapping(status.get("diskStatus"), f"{node} disk status")
        if len(disk_statuses) != 1:
            raise CapacityContractError(f"Longhorn node {node} reports an unexpected disk count")
        observed = _mapping(next(iter(disk_statuses.values())), f"{node} observed disk")
        _conditions_true(observed.get("conditions"), f"{node} disk conditions")
        if (
            observed.get("diskName") != EXPECTED_DISK
            or observed.get("diskType") != "filesystem"
            # Longhorn records the ext-family superblock name returned by
            # statfs (ext2/ext3); the independent host mount report above is
            # still required to prove that the mounted filesystem is ext4.
            or observed.get("filesystemType") != "ext2/ext3"
            or posixpath.normpath(str(observed.get("diskPath", ""))) != EXPECTED_MOUNT
        ):
            raise CapacityContractError(f"Longhorn observed the wrong storage device for {node}")

        maximum = _integer(
            observed.get("storageMaximum"),
            f"{node} storage maximum",
            MINIMUM_FILESYSTEM_BYTES,
        )
        available = _integer(observed.get("storageAvailable"), f"{node} storage available")
        scheduled = _integer(observed.get("storageScheduled"), f"{node} storage scheduled")
        if abs(maximum - mount_capacities[node]["size"]) > FILESYSTEM_CAPACITY_TOLERANCE_BYTES:
            raise CapacityContractError(
                f"Longhorn capacity does not match the dedicated mount for {node}"
            )
        if available > maximum or available * 100 < maximum * MINIMUM_AVAILABLE_PERCENTAGE:
            raise CapacityContractError(f"Longhorn minimum-free-space gate failed for {node}")
        if scheduled > maximum - RESERVED_BYTES:
            raise CapacityContractError(
                f"Longhorn non-overprovisioned scheduling gate failed for {node}"
            )

        maximum_values.append(maximum)
        available_values.append(available)
        scheduled_values.append(scheduled)

    return {
        "longhorn_schedulable_node_count": len(items),
        "longhorn_dedicated_disk_count": len(items),
        "total_storage_maximum_bytes": sum(maximum_values),
        "total_storage_available_bytes": sum(available_values),
        "total_storage_scheduled_bytes": sum(scheduled_values),
        "minimum_node_available_bytes": min(available_values),
        # Losing the node with the most free capacity is the conservative case.
        "worst_case_two_node_available_bytes": sum(available_values) - max(available_values),
        "critical_class_replica_count": 3,
        "critical_class_replicas_after_one_node_loss": 2,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount-report", required=True, type=pathlib.Path)
    parser.add_argument("--longhorn-nodes", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        mount_summary, mount_capacities = validate_mount_report(
            _load_json(args.mount_report, "mount report")
        )
        output: dict[str, Any] = {
            "schema_version": 1,
            "status": "PASS",
            "mode": "pre-install" if args.longhorn_nodes is None else "post-install",
            **mount_summary,
        }
        if args.longhorn_nodes is not None:
            output.update(
                validate_longhorn_nodes(
                    _load_json(args.longhorn_nodes, "Longhorn NodeList"),
                    mount_capacities,
                )
            )
    except (CapacityContractError, OSError) as exc:
        print(f"[FAIL] Longhorn capacity contract: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
