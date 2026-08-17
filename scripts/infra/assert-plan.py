#!/usr/bin/env python3
"""Assert the exact Stage A Terraform plan without persisting full plan JSON."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


EXPECTED_COUNTS = {
    "verda_instance": 3,
    "verda_ssh_key": 1,
    "verda_volume": 3,
}
EXPECTED_INSTANCE_NAMES = {f"verda-mgmt-server-{index:02d}" for index in range(1, 4)}
EXPECTED_VOLUME_NAMES = {f"verda-mgmt-data-{index:02d}" for index in range(1, 4)}
EXPECTED_IMAGE = "77edfb23-bb0d-41cc-a191-dccae45d96fd"
NODE_02_ADDRESS = 'module.management.module.node["02"].verda_instance.this'


def fail(message: str) -> None:
    raise AssertionError(message)


def read_plan(root: pathlib.Path, plan_path: pathlib.Path) -> tuple[dict[str, Any], bytes]:
    command = ["terraform", f"-chdir={root}", "show", "-json", str(plan_path)]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        fail("terraform show failed; raw diagnostic withheld from evidence")
    try:
        return json.loads(result.stdout), result.stdout
    except json.JSONDecodeError as error:
        fail(f"terraform show returned invalid JSON at byte {error.pos}")


def changed_resources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for resource in plan.get("resource_changes", []):
        actions = resource.get("change", {}).get("actions", [])
        if actions not in (["no-op"], ["read"]):
            changes.append(resource)
    return changes


def assert_credentials_absent(raw_plan: bytes) -> None:
    lowered = raw_plan.lower()
    forbidden_labels = (
        b"verda_client_secret",
        b"verda_client_id",
        b"client_secret\"",
    )
    for label in forbidden_labels:
        if label in lowered:
            fail("a forbidden credential label appears in the plan JSON")

    for variable in ("VERDA_CLIENT_ID", "VERDA_CLIENT_SECRET"):
        value = os.environ.get(variable, "").encode()
        if len(value) >= 8 and value in raw_plan:
            fail(f"the value of {variable} appears in the plan JSON")


def assert_output_sensitivity(plan: dict[str, Any]) -> list[str]:
    outputs = plan.get("configuration", {}).get("root_module", {}).get("outputs", {})
    required = {
        "ansible_inventory",
        "cluster_name",
        "data_volume_names",
        "infrastructure_summary",
        "node_names",
        "nodes",
        "public_addresses",
        "ssh_key_fingerprint",
    }
    missing = required - set(outputs)
    if missing:
        fail(f"required root outputs are absent: {sorted(missing)}")
    sensitive = sorted(name for name, value in outputs.items() if value.get("sensitive", False))
    if sensitive:
        fail(f"non-secret inventory outputs were unexpectedly marked sensitive: {sensitive}")
    return sorted(outputs)


def assert_initial_plan(changes: list[dict[str, Any]]) -> dict[str, Any]:
    actions = collections.Counter()
    counts = collections.Counter()
    instances: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []

    for resource in changes:
        resource_type = resource.get("type")
        change_actions = tuple(resource.get("change", {}).get("actions", []))
        actions["/".join(change_actions)] += 1
        if change_actions != ("create",):
            fail(f"initial plan contains a non-create action at {resource.get('address')}")
        if resource_type not in EXPECTED_COUNTS:
            fail(f"initial plan contains non-allowlisted resource type {resource_type}")
        counts[resource_type] += 1
        after = resource.get("change", {}).get("after") or {}
        if resource_type == "verda_instance":
            instances.append(after)
        elif resource_type == "verda_volume":
            volumes.append(after)

    if dict(counts) != EXPECTED_COUNTS:
        fail(f"resource counts differ from the Stage A contract: {dict(counts)}")

    instance_names = {item.get("hostname") for item in instances}
    if instance_names != EXPECTED_INSTANCE_NAMES:
        fail(f"unexpected instance names: {sorted(instance_names)}")
    for instance in instances:
        if instance.get("instance_type") != "CPU.4V.16G":
            fail("an instance does not use CPU.4V.16G")
        if instance.get("image") != "ubuntu-24.04":
            fail("an instance does not use the provider-stable Ubuntu image_type")
        if instance.get("location") != "FIN-03":
            fail("an instance does not use FIN-03")
        if instance.get("is_spot") is not False:
            fail("a management instance is not explicitly on-demand")
        os_volume = instance.get("os_volume") or {}
        if os_volume.get("size") != 80 or os_volume.get("type") != "NVMe":
            fail("an instance does not use an 80 GiB NVMe OS volume")
        if len(instance.get("existing_volumes") or []) != 1:
            fail("an instance does not attach exactly one external data volume")

    volume_names = {item.get("name") for item in volumes}
    if volume_names != EXPECTED_VOLUME_NAMES:
        fail(f"unexpected data-volume names: {sorted(volume_names)}")
    for volume in volumes:
        if volume.get("size") != 100:
            fail("a data volume is not 100 GiB")
        if volume.get("type") != "NVMe" or volume.get("location") != "FIN-03":
            fail("a data volume does not use NVMe in FIN-03")

    return {
        "actions": dict(sorted(actions.items())),
        "resource_counts": dict(sorted(counts.items())),
        "instance_names": sorted(instance_names),
        "data_volume_names": sorted(volume_names),
    }


def assert_compute_rollback(changes: list[dict[str, Any]]) -> dict[str, Any]:
    if len(changes) != 3:
        fail(f"compute rollback must change exactly three resources, found {len(changes)}")
    names = set()
    for resource in changes:
        if resource.get("type") != "verda_instance":
            fail("compute rollback includes a non-instance resource")
        if tuple(resource.get("change", {}).get("actions", [])) != ("delete",):
            fail(f"compute rollback has a non-delete action at {resource.get('address')}")
        before = resource.get("change", {}).get("before") or {}
        names.add(before.get("hostname"))
        if before.get("instance_type") != "CPU.4V.16G":
            fail("compute rollback includes an instance outside the accepted flavor")
        if before.get("image") != "ubuntu-24.04":
            fail("compute rollback includes an instance outside the accepted image")
        if before.get("location") != "FIN-03" or before.get("is_spot") is not False:
            fail("compute rollback includes an instance outside the accepted location/pricing contract")
        os_volume = before.get("os_volume") or {}
        if os_volume.get("size") != 80 or os_volume.get("type") != "NVMe":
            fail("compute rollback includes an unexpected OS-volume contract")
        if len(before.get("existing_volumes") or []) != 1:
            fail("compute rollback does not retain exactly one external data-volume relationship")
    if names != EXPECTED_INSTANCE_NAMES:
        fail(f"compute rollback targets unexpected nodes: {sorted(names)}")
    return {
        "actions": {"delete": 3},
        "resource_counts": {"verda_instance": 3},
        "instance_names": sorted(names),
        "data_volume_names": sorted(EXPECTED_VOLUME_NAMES),
    }


def assert_node_02_replacement(changes: list[dict[str, Any]]) -> dict[str, Any]:
    if len(changes) != 1:
        fail(f"node-02 recovery must change exactly one resource, found {len(changes)}")

    resource = changes[0]
    if resource.get("address") != NODE_02_ADDRESS:
        fail(f"node-02 recovery targets an unexpected address: {resource.get('address')}")
    if resource.get("type") != "verda_instance":
        fail("node-02 recovery includes a non-instance resource")

    action_tuple = tuple(resource.get("change", {}).get("actions", []))
    if action_tuple not in (("delete", "create"), ("create", "delete")):
        fail(f"node-02 recovery is not a replacement action: {'/'.join(action_tuple)}")

    before = resource.get("change", {}).get("before") or {}
    after = resource.get("change", {}).get("after") or {}
    if before.get("hostname") != "verda-mgmt-server-02":
        fail("node-02 recovery has an unexpected existing hostname")
    if after.get("hostname") != "verda-mgmt-server-02":
        fail("node-02 recovery has an unexpected replacement hostname")
    if after.get("instance_type") != "CPU.4V.16G":
        fail("node-02 replacement does not use CPU.4V.16G")
    if after.get("image") != "ubuntu-24.04":
        fail("node-02 replacement does not use the provider-stable Ubuntu image_type")
    if after.get("location") != "FIN-03" or after.get("is_spot") is not False:
        fail("node-02 replacement location or on-demand setting changed")
    os_volume = after.get("os_volume") or {}
    if os_volume.get("size") != 80 or os_volume.get("type") != "NVMe":
        fail("node-02 replacement does not use an 80 GiB NVMe OS volume")

    before_data = before.get("existing_volumes") or []
    after_data = after.get("existing_volumes") or []
    if len(before_data) != 1 or after_data != before_data:
        fail("node-02 recovery does not preserve the exact attached data volume")

    return {
        "actions": {"/".join(action_tuple): 1},
        "resource_counts": {"verda_instance": 1},
        "instance_names": ["verda-mgmt-server-02"],
        "data_volume_names": sorted(EXPECTED_VOLUME_NAMES),
    }


def build_summary(
    plan: dict[str, Any],
    raw_plan: bytes,
    plan_path: pathlib.Path,
    requested_mode: str,
) -> dict[str, Any]:
    assert_credentials_absent(raw_plan)
    outputs = assert_output_sensitivity(plan)
    if requested_mode != "compute-rollback":
        infrastructure_summary = (
            plan.get("planned_values", {})
            .get("outputs", {})
            .get("infrastructure_summary", {})
            .get("value", {})
        )
        if infrastructure_summary.get("os_image_id") != EXPECTED_IMAGE:
            fail("the immutable image configuration ID is absent from the planned summary")
        if infrastructure_summary.get("provider_image_value") != "ubuntu-24.04":
            fail("the provider image transport value is absent from the planned summary")
    changes = changed_resources(plan)
    if requested_mode == "compute-rollback":
        detected_mode = "compute-rollback"
    elif requested_mode == "node-02-replacement":
        detected_mode = "node-02-replacement"
    else:
        detected_mode = "no-drift" if not changes else "initial"
        if requested_mode != "auto" and requested_mode != detected_mode:
            fail(f"expected {requested_mode} plan but detected {detected_mode}")

    details: dict[str, Any]
    if detected_mode == "initial":
        details = assert_initial_plan(changes)
    elif detected_mode == "compute-rollback":
        details = assert_compute_rollback(changes)
    elif detected_mode == "node-02-replacement":
        details = assert_node_02_replacement(changes)
    else:
        details = {
            "actions": {},
            "resource_counts": {},
            "instance_names": sorted(EXPECTED_INSTANCE_NAMES),
            "data_volume_names": sorted(EXPECTED_VOLUME_NAMES),
        }

    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": detected_mode,
        "terraform_format_version": plan.get("format_version"),
        "terraform_version": plan.get("terraform_version"),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "credentials_embedded": False,
        "output_names": outputs,
        "outputs_sensitive": False,
        "selection": {
            "instance_type": "CPU.4V.16G",
            "location": "FIN-03",
            "os_image_id": EXPECTED_IMAGE,
            "root_volume_size_gib": 80,
            "data_volume_size_gib": 100,
            "is_spot": False,
            "preserve_data_volumes": True,
        },
        **details,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--plan", required=True, type=pathlib.Path)
    parser.add_argument("--summary", required=True, type=pathlib.Path)
    parser.add_argument(
        "--mode",
        choices=("auto", "initial", "no-drift", "compute-rollback", "node-02-replacement"),
        default="auto",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan, raw_plan = read_plan(args.root.resolve(), args.plan.resolve())
        summary = build_summary(plan, raw_plan, args.plan.resolve(), args.mode)
    except AssertionError as error:
        print(f"[FAIL] Phase 2 plan assertion: {error}", file=sys.stderr)
        return 1

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        "[PASS] Phase 2 plan assertion: "
        f"mode={summary['mode']} resources={sum(summary['resource_counts'].values())} "
        "credentials=absent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
