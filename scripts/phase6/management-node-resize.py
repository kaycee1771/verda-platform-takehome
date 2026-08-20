#!/usr/bin/env python3
"""Fail-closed admission and execution boundary for a serial management resize.

The controller never accepts credentials as arguments and never emits Terraform,
Kubernetes, or provider output. Terraform and cluster authentication remain in
the already-protected process environment. The checked-in contract is inert by
default; activation requires an exact integrated commit and independent review.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from typing import Any


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_RE = re.compile(r"^0[1-3]$")
ALLOWED_ACTIONS = {("delete", "create"), ("create", "delete")}


class ResizeRefused(RuntimeError):
    """A fail-closed admission refusal safe to present to an operator."""


def refuse(message: str) -> None:
    raise ResizeRefused(message)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        refuse(f"unable to read valid JSON from {path.name}: {type(error).__name__}")
    if not isinstance(value, dict):
        refuse(f"{path.name} must contain one JSON object")
    return value


def digest_file(path: pathlib.Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        refuse(f"unable to hash {path.name}: {type(error).__name__}")


def canonical_digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_time(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str):
        refuse(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        refuse(f"{label} must be an RFC3339 timestamp")
    if parsed.tzinfo is None:
        refuse(f"{label} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        refuse(f"{label} fields differ from contract: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")


def validate_contract(contract: dict[str, Any]) -> None:
    exact_keys(
        contract,
        {
            "schema_version",
            "phase",
            "cluster",
            "activation",
            "terraform",
            "serial",
            "freshness_seconds",
            "required_preflight",
            "required_recovery",
            "required_postflight",
            "evidence",
        },
        "contract",
    )
    if contract["schema_version"] != 1 or contract["phase"] != 6 or contract["cluster"] != "management":
        refuse("contract identity is not Phase 6 management schema v1")

    activation = contract["activation"]
    exact_keys(activation, {"enabled", "writes_allowed", "integrated_commit", "reason"}, "activation")
    if not isinstance(activation["enabled"], bool) or not isinstance(activation["writes_allowed"], bool):
        refuse("activation flags must be booleans")
    commit = activation["integrated_commit"]
    if commit is not None and (not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit)):
        refuse("integrated_commit must be null or an exact lowercase Git SHA-1")

    terraform = contract["terraform"]
    exact_keys(
        terraform,
        {
            "root",
            "source_instance_type",
            "target_instance_type",
            "source_resource_expiry_utc",
            "target_resource_expiry_utc",
            "location",
            "image",
            "root_volume_size_gib",
            "root_volume_type",
            "on_demand",
            "saved_plan_must_be_outside_repository",
            "state_must_be_outside_repository",
        },
        "terraform contract",
    )
    expected_tf = {
        "root": "infra/terraform/environments/management",
        "source_instance_type": "CPU.4V.16G",
        "target_instance_type": "CPU.8V.32G",
        "source_resource_expiry_utc": "2026-08-24T21:00:00Z",
        "location": "FIN-03",
        "image": "ubuntu-24.04",
        "root_volume_size_gib": 80,
        "root_volume_type": "NVMe",
        "on_demand": True,
        "saved_plan_must_be_outside_repository": True,
        "state_must_be_outside_repository": True,
    }
    for key, value in expected_tf.items():
        if terraform.get(key) != value:
            refuse("Terraform resize boundary differs from the exact reviewed shape")
    target_expiry = terraform["target_resource_expiry_utc"]
    if target_expiry is not None:
        parse_time(target_expiry, "terraform.target_resource_expiry_utc")
    if activation["enabled"] and target_expiry is None:
        refuse("active resize contract requires an exact reviewed per-node target expiry")
    if set(terraform) != set(expected_tf) | {"target_resource_expiry_utc"}:
        refuse("Terraform resize boundary differs from the exact reviewed shape")

    serial = contract["serial"]
    exact_keys(
        serial,
        {"resize_order", "rollback_order", "maximum_concurrent_replacements", "addresses", "join_peers"},
        "serial contract",
    )
    if serial["resize_order"] not in (["03", "02", "01"], ["02", "03", "01"]):
        refuse("resize must select nodes 02/03 by leadership evidence and keep node 01 until last")
    if serial["rollback_order"] != list(reversed(serial["resize_order"])):
        refuse("rollback must be serial and reverse the resize order")
    if serial["maximum_concurrent_replacements"] != 1:
        refuse("maximum concurrent replacements must equal one")
    addresses = serial["addresses"]
    if set(addresses) != {"01", "02", "03"}:
        refuse("exactly three management-node addresses are required")
    for node in ("01", "02", "03"):
        expected = f'module.management.module.node["{node}"].verda_instance.this'
        if addresses[node] != expected:
            refuse(f"Terraform address for node {node} differs from contract")
    if serial["join_peers"] != {"01": "02", "02": "01", "03": "01"}:
        refuse("replacement join peers differ from the reviewed survivor map")

    if not isinstance(contract["freshness_seconds"], int) or not 60 <= contract["freshness_seconds"] <= 900:
        refuse("gate freshness must be between 60 and 900 seconds")
    for gate_name in ("required_preflight", "required_recovery", "required_postflight"):
        gates = contract[gate_name]
        if not isinstance(gates, dict) or not gates:
            refuse(f"{gate_name} must be a non-empty exact gate map")
        if any(not isinstance(key, str) or not isinstance(value, (bool, int)) for key, value in gates.items()):
            refuse(f"{gate_name} contains an unsupported gate type")

    evidence = contract["evidence"]
    exact_keys(evidence, {"forbidden_key_fragments", "hash_algorithm", "identity_free"}, "evidence contract")
    if evidence["hash_algorithm"] != "sha256" or evidence["identity_free"] is not True:
        refuse("evidence must be identity-free and SHA-256 bound")
    required_forbidden = {"client_secret", "credential", "kubeconfig", "private_key", "public_ip", "resource_id", "secret", "token"}
    if not required_forbidden.issubset(set(evidence["forbidden_key_fragments"])):
        refuse("evidence forbidden-key policy is incomplete")


def require_activation(contract: dict[str, Any], git_commit: str) -> str:
    activation = contract["activation"]
    if activation["enabled"] is not True or activation["writes_allowed"] is not True:
        refuse("Phase 6 resize activation is disabled; no live action is allowed")
    integrated = activation["integrated_commit"]
    if not isinstance(integrated, str) or not COMMIT_RE.fullmatch(integrated):
        refuse("activation lacks an exact integrated commit")
    if git_commit != integrated:
        refuse("working commit differs from the reviewed integrated commit")
    return integrated


def assert_outside_repository(path: pathlib.Path, repository: pathlib.Path, label: str) -> pathlib.Path:
    resolved = path.resolve()
    root = repository.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    refuse(f"{label} must remain outside the repository")


def expected_node(contract: dict[str, Any], progress: dict[str, Any], direction: str) -> str:
    exact_keys(
        progress,
        {
            "schema_version", "integrated_commit", "completed_resize_nodes", "completed_rollback_nodes",
            "in_flight_node", "in_flight_direction",
        },
        "progress",
    )
    if progress["schema_version"] != 1:
        refuse("progress schema differs from v1")
    resized = progress["completed_resize_nodes"]
    rolled_back = progress["completed_rollback_nodes"]
    if not isinstance(resized, list) or not isinstance(rolled_back, list):
        refuse("progress node sets must be ordered lists")
    if any(not isinstance(node, str) or not NODE_RE.fullmatch(node) for node in resized + rolled_back):
        refuse("progress contains an invalid node ordinal")
    if len(set(resized)) != len(resized) or len(set(rolled_back)) != len(rolled_back):
        refuse("progress contains duplicate node ordinals")

    resize_order = contract["serial"]["resize_order"]
    rollback_order = contract["serial"]["rollback_order"]
    if resized != resize_order[: len(resized)]:
        refuse("completed resize nodes are not an exact serial prefix")
    if rolled_back != rollback_order[: len(rolled_back)]:
        refuse("completed rollback nodes are not an exact serial prefix")

    in_flight = progress["in_flight_node"]
    in_flight_direction = progress["in_flight_direction"]
    if in_flight is not None and (not isinstance(in_flight, str) or not NODE_RE.fullmatch(in_flight)):
        refuse("in-flight node is invalid")
    if (in_flight is None) != (in_flight_direction is None):
        refuse("in-flight node and direction must be set or cleared together")
    if in_flight_direction not in (None, "resize", "rollback"):
        refuse("in-flight direction is invalid")

    if direction == "resize":
        if in_flight is not None:
            refuse("a prior node remains in flight; postflight or rollback must complete first")
        if len(resized) >= len(resize_order):
            refuse("all management nodes are already recorded as resized")
        return resize_order[len(resized)]
    if direction != "rollback":
        refuse("direction must be resize or rollback")

    if in_flight is not None:
        # Immediate recovery of a just-applied node is allowed before progress
        # is advanced, but never of a different node.
        if in_flight_direction != "resize":
            refuse("a rollback operation is already in flight")
        expected_resize = resize_order[len(resized)] if len(resized) < len(resize_order) else None
        if in_flight != expected_resize:
            refuse("in-flight rollback node differs from the next serial resize node")
        return in_flight
    if resized != resize_order:
        refuse("ordered rollback requires a fully resized cluster unless one node is in flight")
    if len(rolled_back) >= len(rollback_order):
        refuse("all management nodes are already recorded as rolled back")
    return rollback_order[len(rolled_back)]


def assert_plan(plan: dict[str, Any], contract: dict[str, Any], node: str, direction: str) -> dict[str, Any]:
    changed = []
    for resource in plan.get("resource_changes", []):
        actions = tuple(resource.get("change", {}).get("actions", []))
        if actions not in {("no-op",), ("read",)}:
            changed.append(resource)
    if len(changed) != 1:
        refuse(f"saved plan must replace exactly one resource; found {len(changed)} changes")

    resource = changed[0]
    expected_address = contract["serial"]["addresses"][node]
    if resource.get("address") != expected_address or resource.get("type") != "verda_instance":
        refuse("saved plan targets an unexpected resource")
    actions = tuple(resource.get("change", {}).get("actions", []))
    if actions not in ALLOWED_ACTIONS:
        refuse("saved plan is not a single replacement")

    change = resource.get("change", {})
    before = change.get("before") or {}
    after = change.get("after") or {}
    tf = contract["terraform"]
    source = tf["source_instance_type"] if direction == "resize" else tf["target_instance_type"]
    target = tf["target_instance_type"] if direction == "resize" else tf["source_instance_type"]
    source_expiry = tf["source_resource_expiry_utc"] if direction == "resize" else tf["target_resource_expiry_utc"]
    target_expiry = tf["target_resource_expiry_utc"] if direction == "resize" else tf["source_resource_expiry_utc"]
    if not isinstance(source_expiry, str) or not isinstance(target_expiry, str):
        refuse("saved plan cannot be admitted without exact source and target expiries")
    hostname = f"verda-mgmt-server-{node}"
    if before.get("hostname") != hostname or after.get("hostname") != hostname:
        refuse("saved plan changes the deterministic hostname")
    if before.get("instance_type") != source or after.get("instance_type") != target:
        refuse("saved plan does not contain the exact requested shape transition")
    before_description = f"verda-mgmt server; owner=platform; expires={source_expiry}"
    after_description = f"verda-mgmt server; owner=platform; expires={target_expiry}"
    if before.get("description") != before_description or after.get("description") != after_description:
        refuse("saved plan does not contain the exact reviewed per-node expiry transition")
    for key, expected in (("image", tf["image"]), ("location", tf["location"]), ("is_spot", not tf["on_demand"])):
        if before.get(key) != expected or after.get(key) != expected:
            refuse(f"saved plan changes protected instance field {key}")
    expected_os = {"name": f"verda-mgmt-os-{node}", "size": tf["root_volume_size_gib"], "type": tf["root_volume_type"]}
    if before.get("os_volume") != expected_os or after.get("os_volume") != expected_os:
        refuse("saved plan changes the protected OS-volume contract")
    before_data = before.get("existing_volumes")
    after_data = after.get("existing_volumes")
    if not isinstance(before_data, list) or len(before_data) != 1 or after_data != before_data:
        refuse("saved plan does not preserve the exact attached data volume")
    if before.get("ssh_key_ids") != after.get("ssh_key_ids"):
        refuse("saved plan changes SSH key attachment")
    if before.get("startup_script_id") != after.get("startup_script_id"):
        refuse("saved plan changes startup-script attachment")

    return {
        "node": node,
        "direction": direction,
        "source_instance_type": source,
        "target_instance_type": target,
        "source_resource_expiry_utc": source_expiry,
        "target_resource_expiry_utc": target_expiry,
        "replacement_count": 1,
        "persistent_data_volume_preserved": True,
    }


def assert_gate_bundle(
    bundle: dict[str, Any],
    required: dict[str, Any],
    integrated_commit: str,
    node: str,
    contract: dict[str, Any],
    now: dt.datetime,
    label: str,
) -> None:
    exact_keys(bundle, {"schema_version", "phase", "cluster", "integrated_commit", "node", "captured_at", "checks"}, label)
    if bundle["schema_version"] != 1 or bundle["phase"] != 6 or bundle["cluster"] != "management":
        refuse(f"{label} identity differs from contract")
    if bundle["integrated_commit"] != integrated_commit or bundle["node"] != node:
        refuse(f"{label} is not bound to this commit and node")
    captured = parse_time(bundle["captured_at"], f"{label}.captured_at")
    age = (now.astimezone(dt.timezone.utc) - captured).total_seconds()
    if age < -30 or age > contract["freshness_seconds"]:
        refuse(f"{label} is stale or from the future")
    checks = bundle["checks"]
    if not isinstance(checks, dict) or checks != required:
        refuse(f"{label} does not exactly satisfy every required gate")


def assert_lease(lease: dict[str, Any], integrated_commit: str, now: dt.datetime) -> None:
    exact_keys(lease, {"schema_version", "phase", "integrated_commit", "owner_digest", "writes_allowed", "expires_at"}, "lease")
    if lease["schema_version"] != 1 or lease["phase"] != 6 or lease["integrated_commit"] != integrated_commit:
        refuse("single-writer lease is not bound to this Phase 6 commit")
    if not isinstance(lease["owner_digest"], str) or not DIGEST_RE.fullmatch(lease["owner_digest"]):
        refuse("single-writer lease owner must be represented only by a SHA-256 digest")
    if lease["writes_allowed"] is not True:
        refuse("single-writer lease does not allow writes")
    if parse_time(lease["expires_at"], "lease.expires_at") <= now.astimezone(dt.timezone.utc):
        refuse("single-writer lease has expired")


def assert_review(
    review: dict[str, Any], integrated_commit: str, node: str, direction: str,
    plan_sha: str, gate_sha: str, contract_sha: str,
) -> None:
    exact_keys(
        review,
        {
            "schema_version", "phase", "integrated_commit", "node", "direction",
            "plan_sha256", "preflight_sha256", "contract_sha256", "author_digest",
            "reviewer_digest", "security_approved", "capacity_approved",
        },
        "review",
    )
    expected = {
        "schema_version": 1,
        "phase": 6,
        "integrated_commit": integrated_commit,
        "node": node,
        "direction": direction,
        "plan_sha256": plan_sha,
        "preflight_sha256": gate_sha,
        "contract_sha256": contract_sha,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            refuse(f"review {key} is not bound to this execution")
    for key in ("author_digest", "reviewer_digest"):
        if not isinstance(review[key], str) or not DIGEST_RE.fullmatch(review[key]):
            refuse(f"review {key} must be an identity-free SHA-256 digest")
    if review["author_digest"] == review["reviewer_digest"]:
        refuse("author and independent reviewer must differ")
    if review["security_approved"] is not True or review["capacity_approved"] is not True:
        refuse("security and capacity reviews must both approve the exact execution")


def terraform_show(terraform_root: pathlib.Path, saved_plan: pathlib.Path) -> dict[str, Any]:
    result = subprocess.run(
        ["terraform", f"-chdir={terraform_root}", "show", "-json", str(saved_plan)],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        refuse("terraform show failed; raw diagnostic withheld")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        refuse("terraform show returned invalid JSON; raw output withheld")
    if not isinstance(value, dict):
        refuse("terraform show did not return one plan object")
    return value


def admission(
    *, contract_path: pathlib.Path, progress_path: pathlib.Path, saved_plan: pathlib.Path,
    preflight_path: pathlib.Path, review_path: pathlib.Path, lease_path: pathlib.Path,
    direction: str, git_commit: str, repository: pathlib.Path,
    now: dt.datetime | None = None, plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    contract = read_json(contract_path)
    validate_contract(contract)
    integrated = require_activation(contract, git_commit)
    contract_sha = digest_file(contract_path)
    progress = read_json(progress_path)
    if progress["integrated_commit"] != integrated:
        refuse("progress is not bound to the integrated commit")
    node = expected_node(contract, progress, direction)
    plan_path = assert_outside_repository(saved_plan, repository, "saved plan")
    if not plan_path.is_file():
        refuse("saved plan is absent")
    plan_sha = digest_file(plan_path)
    plan_value = plan if plan is not None else terraform_show(repository / contract["terraform"]["root"], plan_path)
    details = assert_plan(plan_value, contract, node, direction)

    preflight = read_json(preflight_path)
    assert_gate_bundle(preflight, contract["required_preflight"], integrated, node, contract, now, "preflight")
    gate_sha = digest_file(preflight_path)
    lease = read_json(lease_path)
    assert_lease(lease, integrated, now)
    review = read_json(review_path)
    assert_review(review, integrated, node, direction, plan_sha, gate_sha, contract_sha)

    return {
        "schema_version": 1,
        "status": "ADMITTED",
        "phase": 6,
        "cluster": "management",
        "direction": direction,
        "node": node,
        "source_instance_type": details["source_instance_type"],
        "target_instance_type": details["target_instance_type"],
        "target_resource_expiry_utc": details["target_resource_expiry_utc"],
        "replacement_count": 1,
        "persistent_data_volume_preserved": True,
        "plan_sha256": plan_sha,
        "preflight_sha256": gate_sha,
        "contract_sha256": contract_sha,
        "reviewer_count": 2,
        "all_preflight_gates_passed": True,
    }


def verify_postflight(
    contract_path: pathlib.Path, postflight_path: pathlib.Path, node: str,
    git_commit: str, now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    contract = read_json(contract_path)
    validate_contract(contract)
    integrated = require_activation(contract, git_commit)
    if not NODE_RE.fullmatch(node):
        refuse("postflight node is invalid")
    postflight = read_json(postflight_path)
    assert_gate_bundle(postflight, contract["required_postflight"], integrated, node, contract, now, "postflight")
    return {
        "schema_version": 1,
        "status": "POSTFLIGHT_PASS",
        "phase": 6,
        "cluster": "management",
        "node": node,
        "postflight_sha256": digest_file(postflight_path),
        "all_postflight_gates_passed": True,
    }


def recovery_admission(
    *, contract_path: pathlib.Path, progress_path: pathlib.Path, recovery_path: pathlib.Path,
    lease_path: pathlib.Path, direction: str, git_commit: str, repository: pathlib.Path,
    inventory_path: pathlib.Path, private_key_path: pathlib.Path, known_hosts_path: pathlib.Path,
    runtime_vars_path: pathlib.Path, now: dt.datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    now = now or dt.datetime.now(dt.timezone.utc)
    contract = read_json(contract_path)
    validate_contract(contract)
    integrated = require_activation(contract, git_commit)
    progress = read_json(progress_path)
    exact_keys(
        progress,
        {
            "schema_version", "integrated_commit", "completed_resize_nodes", "completed_rollback_nodes",
            "in_flight_node", "in_flight_direction",
        },
        "progress",
    )
    if progress["schema_version"] != 1 or progress["integrated_commit"] != integrated:
        refuse("recovery progress is not bound to the integrated commit")
    node = progress["in_flight_node"]
    if not isinstance(node, str) or not NODE_RE.fullmatch(node) or progress["in_flight_direction"] != direction:
        refuse("recovery requires the exact applied node and direction to be in flight")
    resized = progress["completed_resize_nodes"]
    rolled_back = progress["completed_rollback_nodes"]
    if direction == "resize":
        expected = contract["serial"]["resize_order"][len(resized)] if len(resized) < 3 else None
    else:
        if resized != contract["serial"]["resize_order"]:
            refuse("ordered rollback recovery requires the fully resized prefix")
        expected = contract["serial"]["rollback_order"][len(rolled_back)] if len(rolled_back) < 3 else None
    if node != expected:
        refuse("recovery node differs from the exact serial prefix")

    recovery = read_json(recovery_path)
    assert_gate_bundle(recovery, contract["required_recovery"], integrated, node, contract, now, "recovery")
    assert_lease(read_json(lease_path), integrated, now)

    inventory = assert_outside_repository(inventory_path, repository, "recovery inventory")
    private_key = assert_outside_repository(private_key_path, repository, "SSH private key")
    known_hosts = assert_outside_repository(known_hosts_path, repository, "known-hosts file")
    runtime_vars = assert_outside_repository(runtime_vars_path, repository, "runtime variables")
    for path, label in (
        (inventory, "recovery inventory"), (private_key, "SSH private key"),
        (known_hosts, "known-hosts file"), (runtime_vars, "runtime variables"),
    ):
        if not path.is_file():
            refuse(f"{label} is absent")
    inventory_text = inventory.read_text(encoding="utf-8")
    if inventory_text.count("verda-mgmt-server-01:") != 1 or inventory_text.count("verda-mgmt-server-02:") != 1 or inventory_text.count("verda-mgmt-server-03:") != 1:
        refuse("recovery inventory does not contain the exact three-node topology")
    if "StrictHostKeyChecking=yes" not in inventory_text or "StrictHostKeyChecking=accept-new" in inventory_text:
        refuse("recovery inventory does not enforce the verified SSH host-key boundary")
    if str(private_key) not in inventory_text or str(known_hosts) not in inventory_text:
        refuse("recovery inventory is not bound to the selected external SSH files")

    join_peer = contract["serial"]["join_peers"][node]
    other_survivor = ({"01", "02", "03"} - {node, join_peer}).pop()
    playbook = repository / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml"
    command = [
        "ansible-playbook", "--inventory", str(inventory), str(playbook),
        "--extra-vars", f"@{runtime_vars}",
        "--extra-vars", f"phase6_resize_target=verda-mgmt-server-{node}",
        "--extra-vars", f"phase6_join_peer=verda-mgmt-server-{join_peer}",
        "--extra-vars", f"phase6_other_survivor=verda-mgmt-server-{other_survivor}",
    ]
    return (
        {
            "schema_version": 1,
            "status": "RECOVERY_ADMITTED",
            "phase": 6,
            "cluster": "management",
            "direction": direction,
            "node": node,
            "join_peer_node": join_peer,
            "other_survivor_node": other_survivor,
            "inventory_sha256": digest_file(inventory),
            "known_hosts_sha256": digest_file(known_hosts),
            "recovery_gate_sha256": digest_file(recovery_path),
            "all_recovery_gates_passed": True,
        },
        command,
    )


def current_commit(repository: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=False, capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or not COMMIT_RE.fullmatch(commit):
        refuse("unable to resolve the exact Git commit")
    return commit


def emit(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    parser.add_argument("--contract", type=pathlib.Path, default=pathlib.Path("config/phase6-management-resize.json"))
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("validate-contract")

    for name in ("admit", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--direction", choices=("resize", "rollback"), required=True)
        command.add_argument("--progress", type=pathlib.Path, required=True)
        command.add_argument("--saved-plan", type=pathlib.Path, required=True)
        command.add_argument("--preflight", type=pathlib.Path, required=True)
        command.add_argument("--review", type=pathlib.Path, required=True)
        command.add_argument("--lease", type=pathlib.Path, required=True)
        if name == "apply":
            command.add_argument("--confirm", required=True)

    recover = sub.add_parser("recover")
    recover.add_argument("--direction", choices=("resize", "rollback"), required=True)
    recover.add_argument("--progress", type=pathlib.Path, required=True)
    recover.add_argument("--recovery", type=pathlib.Path, required=True)
    recover.add_argument("--lease", type=pathlib.Path, required=True)
    recover.add_argument("--inventory", type=pathlib.Path, required=True)
    recover.add_argument("--private-key", type=pathlib.Path, required=True)
    recover.add_argument("--known-hosts", type=pathlib.Path, required=True)
    recover.add_argument("--runtime-vars", type=pathlib.Path, required=True)
    recover.add_argument("--confirm", required=True)

    post = sub.add_parser("verify-postflight")
    post.add_argument("--node", required=True)
    post.add_argument("--postflight", type=pathlib.Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repository = args.repository.resolve()
    contract_path = args.contract if args.contract.is_absolute() else repository / args.contract
    try:
        contract = read_json(contract_path)
        validate_contract(contract)
        if args.action == "validate-contract":
            emit({"schema_version": 1, "status": "VALID_INERT_CONTRACT", "activation_enabled": contract["activation"]["enabled"]})
            return 0

        git_commit = current_commit(repository)
        if args.action == "verify-postflight":
            emit(verify_postflight(contract_path, args.postflight, args.node, git_commit))
            return 0

        if args.action == "recover":
            summary, command = recovery_admission(
                contract_path=contract_path,
                progress_path=args.progress,
                recovery_path=args.recovery,
                lease_path=args.lease,
                direction=args.direction,
                git_commit=git_commit,
                repository=repository,
                inventory_path=args.inventory,
                private_key_path=args.private_key,
                known_hosts_path=args.known_hosts,
                runtime_vars_path=args.runtime_vars,
            )
            expected_confirmation = f"PHASE6_SERIAL_RECOVER_{args.direction.upper()}_{summary['node']}"
            if args.confirm != expected_confirmation:
                refuse("typed recovery confirmation does not match the exact node and direction")
            result = subprocess.run(command, check=False, capture_output=True)
            if result.returncode != 0:
                refuse("bounded host/RKE2 recovery failed; raw diagnostic withheld; keep lease and assess rollback")
            summary["status"] = "RECOVERY_COMPLETE_POSTFLIGHT_REQUIRED"
            emit(summary)
            return 0

        summary = admission(
            contract_path=contract_path,
            progress_path=args.progress,
            saved_plan=args.saved_plan,
            preflight_path=args.preflight,
            review_path=args.review,
            lease_path=args.lease,
            direction=args.direction,
            git_commit=git_commit,
            repository=repository,
        )
        if args.action == "admit":
            emit(summary)
            return 0

        expected_confirmation = f"PHASE6_SERIAL_{args.direction.upper()}_{summary['node']}"
        if args.confirm != expected_confirmation:
            refuse("typed confirmation does not match the exact node and direction")
        terraform_root = repository / contract["terraform"]["root"]
        result = subprocess.run(
            ["terraform", f"-chdir={terraform_root}", "apply", "-input=false", "-lock-timeout=60s", str(args.saved_plan.resolve())],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            refuse("saved-plan apply failed; raw diagnostic withheld; keep lease and begin bounded rollback assessment")
        summary["status"] = "APPLY_COMPLETE_RECOVERY_REQUIRED"
        emit(summary)
        return 0
    except ResizeRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
