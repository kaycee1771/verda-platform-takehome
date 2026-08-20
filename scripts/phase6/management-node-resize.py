#!/usr/bin/env python3
"""Fail-closed preparatory boundary for a future serial management resize.

The controller never accepts credentials as arguments and never emits Terraform,
Kubernetes, or provider output. Terraform and cluster authentication remain in
the already-protected process environment. The checked-in contract is inert by
default. The CLI intentionally exposes contract validation only; no live
mutation, recovery, or progress-advancement action is registered.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_RE = re.compile(r"^0[1-3]$")


class ResizeRefused(RuntimeError):
    """A fail-closed admission refusal safe to present to an operator."""


class ExclusiveLease:
    """A real non-blocking OS lock, not an authorization JSON assertion."""

    def __init__(self, path: pathlib.Path, operation_id: str) -> None:
        self.path = path
        self.operation_id = operation_id
        self.handle: Any = None

    def __enter__(self) -> "ExclusiveLease":
        if not DIGEST_RE.fullmatch(self.operation_id):
            refuse("OS-exclusive lease operation nonce is invalid")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            self.handle.close()
            self.handle = None
            refuse("another controller holds the OS-exclusive live-mutation lease")
        metadata = json.dumps(
            {"schema_version": 1, "phase": 6, "operation_id": self.operation_id, "pid": os.getpid()},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(metadata)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


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


def assert_clean_reviewed_worktree(repository: pathlib.Path, integrated_commit: str) -> None:
    head = current_commit(repository)
    if head != integrated_commit:
        refuse("working commit differs from the reviewed integrated commit")
    result = subprocess.run(
        ["git", "status", "--porcelain=v2", "--untracked-files=all"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip():
        refuse("reviewed worktree is not exactly clean")
    for argv in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(argv, cwd=repository, check=False, capture_output=True).returncode != 0:
            refuse("reviewed worktree contains an uncommitted critical-surface change")


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
            "generation", "used_operation_ids", "in_flight_node", "in_flight_direction",
            "in_flight_operation_id", "in_flight_plan_sha256", "in_flight_recovery_sha256",
            "in_flight_started_at",
        },
        "progress",
    )
    if progress["schema_version"] != 1:
        refuse("progress schema differs from v1")
    if not isinstance(progress["generation"], int) or progress["generation"] < 0:
        refuse("progress generation is invalid")
    used = progress["used_operation_ids"]
    if not isinstance(used, list) or len(set(used)) != len(used) or any(not DIGEST_RE.fullmatch(str(item)) for item in used):
        refuse("used-once operation journal is invalid")
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
    in_flight_metadata = (
        progress["in_flight_operation_id"], progress["in_flight_plan_sha256"],
        progress["in_flight_recovery_sha256"], progress["in_flight_started_at"],
    )
    if in_flight is None and any(item is not None for item in in_flight_metadata):
        refuse("cleared progress retains stale in-flight metadata")
    if in_flight is not None:
        operation_id, plan_sha, recovery_sha, started_at = in_flight_metadata
        if not isinstance(operation_id, str) or not DIGEST_RE.fullmatch(operation_id) or operation_id not in used:
            refuse("in-flight operation is absent from the used-once journal")
        if not isinstance(plan_sha, str) or not DIGEST_RE.fullmatch(plan_sha):
            refuse("in-flight saved-plan digest is invalid")
        if recovery_sha is not None and (not isinstance(recovery_sha, str) or not DIGEST_RE.fullmatch(recovery_sha)):
            refuse("in-flight recovery digest is invalid")
        parse_time(started_at, "progress.in_flight_started_at")

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


def write_json_atomic(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".new", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def transition_progress(
    progress: dict[str, Any], contract: dict[str, Any], *, event: str, direction: str,
    node: str, operation_id: str, plan_sha256: str, recovery_sha256: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    candidate = json.loads(json.dumps(progress))
    if not DIGEST_RE.fullmatch(operation_id) or not DIGEST_RE.fullmatch(plan_sha256):
        refuse("operation or plan digest is invalid")
    if event == "apply":
        if operation_id in candidate["used_operation_ids"]:
            refuse("operation nonce has already been consumed")
        if candidate["in_flight_node"] is not None:
            if not (
                direction == "rollback"
                and candidate["in_flight_direction"] == "resize"
                and candidate["in_flight_node"] == node
            ):
                refuse("another operation remains in flight")
        else:
            expected = expected_node(contract, candidate, direction)
            if expected != node:
                refuse("apply node differs from the exact serial prefix")
        candidate["used_operation_ids"].append(operation_id)
        candidate["in_flight_node"] = node
        candidate["in_flight_direction"] = direction
        candidate["in_flight_operation_id"] = operation_id
        candidate["in_flight_plan_sha256"] = plan_sha256
        candidate["in_flight_recovery_sha256"] = None
        candidate["in_flight_started_at"] = captured_at or dt.datetime.now(dt.timezone.utc).isoformat()
    elif event == "recovery":
        if (
            candidate["in_flight_node"] != node
            or candidate["in_flight_direction"] != direction
            or candidate["in_flight_operation_id"] != operation_id
            or candidate["in_flight_plan_sha256"] != plan_sha256
        ):
            refuse("recovery is not bound to the in-flight operation and saved plan")
        if recovery_sha256 is None or not DIGEST_RE.fullmatch(recovery_sha256):
            refuse("recovery digest is invalid")
        if candidate["in_flight_recovery_sha256"] is not None:
            refuse("recovery has already been recorded")
        candidate["in_flight_recovery_sha256"] = recovery_sha256
    elif event == "postflight":
        if (
            candidate["in_flight_node"] != node
            or candidate["in_flight_direction"] != direction
            or candidate["in_flight_operation_id"] != operation_id
            or candidate["in_flight_plan_sha256"] != plan_sha256
            or candidate["in_flight_recovery_sha256"] != recovery_sha256
        ):
            refuse("postflight is stale or not bound to apply and recovery")
        if direction == "resize":
            candidate["completed_resize_nodes"].append(node)
        else:
            fully_resized = candidate["completed_resize_nodes"] == contract["serial"]["resize_order"]
            if fully_resized and node not in candidate["completed_rollback_nodes"]:
                candidate["completed_rollback_nodes"].append(node)
        candidate["in_flight_node"] = None
        candidate["in_flight_direction"] = None
        candidate["in_flight_operation_id"] = None
        candidate["in_flight_plan_sha256"] = None
        candidate["in_flight_recovery_sha256"] = None
        candidate["in_flight_started_at"] = None
    else:
        refuse("unknown progress transition")
    candidate["generation"] += 1
    return candidate


def assert_plan(
    plan: dict[str, Any], contract: dict[str, Any], node: str, direction: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if plan.get("complete") is not True:
        refuse("saved plan is incomplete or was created with targeting")
    if plan.get("applyable") is not True or plan.get("errored") is not False:
        refuse("saved plan is not complete, applyable, and error-free")
    if plan.get("resource_drift") != []:
        refuse("saved plan resource-drift section is absent or non-empty")
    for marker in ("target_addrs", "targets", "targeting", "incomplete"):
        if marker in plan and plan[marker] not in (None, False, [], {}):
            refuse("saved plan contains a targeting or incomplete-plan marker")
    timestamp = parse_time(plan.get("timestamp"), "plan.timestamp")
    age = (now.astimezone(dt.timezone.utc) - timestamp).total_seconds()
    if age < -30 or age > 3600:
        refuse("saved plan timestamp is older than the one-hour review boundary")
    if plan.get("format_version") != "1.2":
        refuse("saved plan JSON format differs from the accepted v1.2 schema")
    terraform_version = plan.get("terraform_version")
    if terraform_version != "1.15.8":
        refuse("saved plan Terraform version differs from the exact pinned 1.15.8 toolchain")
    configuration = plan.get("configuration")
    prior_state = plan.get("prior_state")
    if not isinstance(configuration, dict) or not configuration or not isinstance(prior_state, dict):
        refuse("saved plan lacks complete configuration or prior-state metadata")
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
    if actions != ("delete", "create"):
        refuse("saved plan must use the exact delete-then-create replacement order")

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
        "configuration_sha256": canonical_digest(configuration),
        "prior_state_sha256": canonical_digest(prior_state),
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
    """Evaluate legacy review fixtures only; this result never authorizes mutation."""
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
    details = assert_plan(plan_value, contract, node, direction, now)

    preflight = read_json(preflight_path)
    assert_gate_bundle(preflight, contract["required_preflight"], integrated, node, contract, now, "preflight")
    gate_sha = digest_file(preflight_path)
    lease = read_json(lease_path)
    assert_lease(lease, integrated, now)
    review = read_json(review_path)
    assert_review(review, integrated, node, direction, plan_sha, gate_sha, contract_sha)

    return {
        "schema_version": 1,
        "status": "PREPARATORY_ANALYSIS_ONLY",
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
    refuse(
        "postflight advancement is disabled until trusted collectors, the pinned recovery runner, "
        "and atomic journal integration are complete"
    )


def recovery_admission(
    *, contract_path: pathlib.Path, progress_path: pathlib.Path, recovery_path: pathlib.Path,
    lease_path: pathlib.Path, direction: str, git_commit: str, repository: pathlib.Path,
    inventory_path: pathlib.Path, private_key_path: pathlib.Path, known_hosts_path: pathlib.Path,
    runtime_vars_path: pathlib.Path, now: dt.datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    refuse(
        "host recovery is disabled until the pinned container runner, canonical input review, "
        "and trusted collector chain are complete"
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

        refuse("unsupported controller action")
    except ResizeRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
