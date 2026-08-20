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
import ipaddress
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any

import yaml


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_RE = re.compile(r"^0[1-3]$")
QUALITY_IMAGE = "verda-platform-quality:phase1-2026-08-16"
RECOVERY_ENV_ALLOWLIST = (
    "HOME=/tmp/home",
    "ANSIBLE_CONFIG=/workspace/infra/ansible/ansible.cfg",
    "ANSIBLE_LOCAL_TEMP=/tmp/ansible-local",
    "PHASE4_RKE2_TOKEN",
    "PHASE4_S3_ENDPOINT",
    "PHASE4_S3_BUCKET",
    "PHASE4_S3_REGION",
    "PHASE4_S3_ACCESS_KEY",
    "PHASE4_S3_SECRET_KEY",
    "PHASE4_S3_SESSION_TOKEN",
)


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
        assert_no_link_path(self.path.parent, "OS-exclusive lease directory")
        created = False
        try:
            self.handle = self.path.open("x+b")
            created = True
        except FileExistsError:
            assert_no_link_path(self.path, "OS-exclusive lease file", single_identity=True)
            self.handle = self.path.open("r+b")
        if created:
            self.handle.write(b"\0")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        self.handle.seek(0, os.SEEK_END)
        status = os.fstat(self.handle.fileno())
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or self.handle.tell() < 1:
            self.handle.close()
            self.handle = None
            refuse("OS-exclusive lease file identity or length is unsafe")
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


def assert_no_link_path(path: pathlib.Path, label: str, *, single_identity: bool = False) -> pathlib.Path:
    """Reject symlink/reparse traversal and hardlinked protected files without following aliases."""
    absolute = path.absolute()
    cursor = absolute
    while True:
        try:
            status = cursor.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & 0x400:
                refuse(f"{label} must not traverse a symlink, junction, or reparse point")
            if single_identity and cursor == absolute and stat.S_ISREG(status.st_mode) and status.st_nlink != 1:
                refuse(f"{label} must have one file identity")
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return absolute.resolve(strict=False)


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
            "cost",
            "capacity",
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
    if contract["cost"] != {
        "target_price_per_instance_hour_usd": 0.0558,
        "approved_seven_day_envelope_usd": 66.6747,
        "minimum_balance_with_reserve_usd": 70.46,
    }:
        refuse("cost contract differs from the reviewed CPU.8V.32G ceiling and reserve")
    if contract["capacity"] != {
        "minimum_per_node_cpu_millicores": 6793,
        "minimum_per_node_memory_bytes": 13659799552,
        "minimum_worst_two_cpu_millicores": 13585,
        "minimum_worst_two_memory_bytes": 27319599104,
    }:
        refuse("capacity contract differs from the checksum-bound projection thresholds")
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


def assert_external_regular_file(
    path: pathlib.Path, repository: pathlib.Path, label: str, *, secret: bool = False,
) -> pathlib.Path:
    assert_no_link_path(path, label, single_identity=True)
    resolved = assert_outside_repository(path, repository, label)
    if not resolved.is_file():
        refuse(f"{label} is absent or is not a regular file")
    cursor = path.absolute()
    while cursor != cursor.parent:
        try:
            status = cursor.lstat()
        except FileNotFoundError:
            cursor = cursor.parent
            continue
        if cursor.is_symlink() or getattr(status, "st_file_attributes", 0) & 0x400:
            refuse(f"{label} traverses a symlink or reparse point")
        cursor = cursor.parent
    if secret and os.name != "nt" and (resolved.stat().st_mode & 0o077):
        refuse(f"{label} permissions are broader than owner-only")
    return resolved


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    value: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            refuse("recovery input contains a duplicate mapping key")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def canonical_recovery_inputs(
    *, repository: pathlib.Path, inventory_path: pathlib.Path, runtime_vars_path: pathlib.Path,
    private_key_path: pathlib.Path, public_key_path: pathlib.Path, known_hosts_path: pathlib.Path,
) -> dict[str, Any]:
    inventory_file = assert_external_regular_file(inventory_path, repository, "recovery inventory")
    runtime_file = assert_external_regular_file(runtime_vars_path, repository, "runtime variables")
    private_key = assert_external_regular_file(private_key_path, repository, "SSH private key", secret=True)
    public_key = assert_external_regular_file(public_key_path, repository, "SSH public key")
    known_hosts = assert_external_regular_file(known_hosts_path, repository, "verified known-hosts file")
    files = [inventory_file, runtime_file, private_key, public_key, known_hosts]
    if len({str(path).casefold() for path in files}) != len(files):
        refuse("recovery inputs must be distinct external files")
    for index, left in enumerate(files):
        for right in files[index + 1:]:
            try:
                if os.path.samefile(left, right):
                    refuse("recovery inputs must not share one file identity")
            except OSError:
                refuse("recovery input file identity could not be verified")
    try:
        inventory = yaml.load(inventory_file.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        hosts = inventory["all"]["children"]["management_servers"]["hosts"]
        runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        refuse(f"recovery inventory/runtime parsing failed: {type(error).__name__}")
    names = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]
    if not isinstance(hosts, dict) or sorted(hosts) != names:
        refuse("recovery inventory differs from the exact management topology")
    expected_fields = {
        "ansible_host", "ansible_user", "ansible_ssh_private_key_file", "ansible_ssh_common_args",
        "node_name", "role", "internal_ip", "wireguard_ip", "data_volume_id",
        "attached_device_id", "data_volume_size_gib",
    }
    addresses: list[str] = []
    internal_addresses: list[str] = []
    wireguard_addresses: list[str] = []
    exact_ssh = (
        "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
        "-o UserKnownHostsFile=/run/config/known_hosts"
    )
    for name in names:
        host = hosts[name]
        if not isinstance(host, dict) or set(host) != expected_fields:
            refuse("recovery inventory host fields differ from the exact schema")
        try:
            ipaddress.ip_address(host["ansible_host"])
            ipaddress.ip_address(host["internal_ip"])
            ipaddress.ip_address(host["wireguard_ip"])
        except ValueError:
            refuse("recovery inventory contains an invalid endpoint")
        addresses.append(str(host["ansible_host"]))
        internal_addresses.append(str(host["internal_ip"]))
        wireguard_addresses.append(str(host["wireguard_ip"]))
        if (
            host["node_name"] != name
            or host["role"] != "server"
            or host["ansible_user"] != "root"
            or host["ansible_ssh_private_key_file"] != "/tmp/phase3-ssh-key"
            or host["ansible_ssh_common_args"] != exact_ssh
            or host["data_volume_size_gib"] != 100
            or host["data_volume_id"] != host["attached_device_id"]
            or host["wireguard_ip"] != f"10.250.0.1{name[-1]}"
        ):
            refuse("recovery inventory identity, SSH, or volume contract differs")
    if any(len(set(values)) != 3 for values in (addresses, internal_addresses, wireguard_addresses)):
        refuse("recovery inventory endpoints are not unique")
    if not isinstance(runtime, dict) or set(runtime) != {"phase3_admin_cidrs_v4", "phase4_cluster_firewall_enabled"}:
        refuse("runtime variables differ from the exact checked schema")
    cidrs = runtime["phase3_admin_cidrs_v4"]
    if not isinstance(cidrs, list) or not cidrs or runtime["phase4_cluster_firewall_enabled"] is not True:
        refuse("runtime variables lack canonical administrative CIDRs or firewall enablement")
    try:
        networks = [ipaddress.ip_network(item, strict=True) for item in cidrs]
    except (TypeError, ValueError):
        refuse("runtime administrative CIDRs are invalid or non-canonical")
    if any(network.version != 4 for network in networks) or cidrs != sorted(set(map(str, networks))):
        refuse("runtime administrative CIDRs must be unique sorted canonical IPv4 networks")
    public_text = public_key.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,3}(?: [^\r\n]+)?", public_text):
        refuse("SSH public key does not use the exact Ed25519 descriptor format")
    return {
        "inventory": inventory,
        "hosts": hosts,
        "paths": {
            "inventory": inventory_file,
            "runtime": runtime_file,
            "private": private_key,
            "public": public_key,
            "known": known_hosts,
        },
        "hashes": {
            "inventory_sha256": digest_file(inventory_file),
            "runtime_vars_sha256": digest_file(runtime_file),
            "ssh_public_sha256": digest_file(public_key),
            "host_trust_sha256": digest_file(known_hosts),
        },
    }


def build_phase6_docker_command(
    *, repository: pathlib.Path, mode: str, node: str, survivor: str,
    inventory_path: pathlib.Path, runtime_vars_path: pathlib.Path, private_key_path: pathlib.Path,
    public_key_path: pathlib.Path, known_hosts_path: pathlib.Path,
) -> tuple[list[str], dict[str, Any]]:
    if mode not in {"prepare", "recover"} or node not in {"01", "02", "03"} or survivor not in {"01", "02", "03"}:
        refuse("recovery runner mode, target, or survivor is invalid")
    if survivor == node:
        refuse("recovery runner survivor must differ from the target")
    if mode == "recover" and survivor != {"01": "02", "02": "01", "03": "01"}[node]:
        refuse("recovery runner join survivor differs from the exact serial contract")
    inputs = canonical_recovery_inputs(
        repository=repository, inventory_path=inventory_path, runtime_vars_path=runtime_vars_path,
        private_key_path=private_key_path, public_key_path=public_key_path, known_hosts_path=known_hosts_path,
    )
    target_name = f"verda-mgmt-server-{node}"
    survivor_name = f"verda-mgmt-server-{survivor}"
    if mode == "recover":
        playbook = "recover-resized-management-node.yml"
        other = ({"01", "02", "03"} - {node, survivor}).pop()
        controls = {
            "phase6_join_peer": survivor_name,
            "phase6_other_survivor": f"verda-mgmt-server-{other}",
            "phase6_resize_target": target_name,
        }
    else:
        playbook = "prepare-management-node-resize.yml"
        controls = {"phase6_prepare_survivor": survivor_name, "phase6_resize_target": target_name}
    playbook_path = repository / "infra" / "ansible" / "playbooks" / playbook
    group_vars_path = repository / "infra" / "ansible" / "inventories" / "group_vars" / "management_servers.yml"
    versions_path = repository / "versions.lock.yaml"
    for path, label in ((playbook_path, "Phase 6 playbook"), (group_vars_path, "management group vars")):
        if not path.is_file() or path.is_symlink():
            refuse(f"{label} is absent or not a checked-in regular file")
    try:
        locked_image = yaml.safe_load(versions_path.read_text(encoding="utf-8"))["tool_delivery"]["quality_image"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as error:
        refuse(f"quality-image lock could not be parsed: {type(error).__name__}")
    if locked_image != QUALITY_IMAGE:
        refuse("recovery quality image differs from the checked-in exact tool lock")
    extra = " ".join(f"--extra-vars '{key}={controls[key]}'" for key in sorted(controls))
    shell_command = (
        "install -d -m 0700 /tmp/home && "
        "install -m 0600 /run/source/phase4-ssh-key /tmp/phase3-ssh-key && "
        f"exec ansible-playbook --inventory /run/config/phase6-inventory.yml playbooks/{playbook} "
        "--extra-vars @inventories/group_vars/management_servers.yml "
        f"--extra-vars @/run/config/phase6-runtime.json {extra}"
    )
    paths = inputs["paths"]
    command = [
        "docker", "run", "--rm", "--network", "bridge", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--pids-limit", "512",
        "--volume", f"{repository.resolve()}:/workspace:ro",
        "--volume", f"{paths['inventory']}:/run/config/phase6-inventory.yml:ro",
        "--volume", f"{paths['runtime']}:/run/config/phase6-runtime.json:ro",
        "--volume", f"{paths['private']}:/run/source/phase4-ssh-key:ro",
        "--volume", f"{paths['public']}:/run/secrets/phase3_ssh_key.pub:ro",
        "--volume", f"{paths['known']}:/run/config/known_hosts:ro",
        "--workdir", "/workspace/infra/ansible",
    ]
    for environment in RECOVERY_ENV_ALLOWLIST:
        command.extend(("--env", environment))
    command.extend((QUALITY_IMAGE, "bash", "-lc", shell_command))
    receipt = {
        "schema_version": 1,
        "status": "DORMANT_COMMAND_REVIEW_ONLY",
        "mode": mode,
        "node": node,
        "survivor_node": survivor,
        **inputs["hashes"],
        "playbook_sha256": digest_file(playbook_path),
        "group_vars_sha256": digest_file(group_vars_path),
        "versions_lock_sha256": digest_file(versions_path),
        "container_image_sha256": hashlib.sha256(QUALITY_IMAGE.encode()).hexdigest(),
        "command_sha256": canonical_digest(command),
    }
    return command, receipt


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


class OperationJournal:
    """Crash-safe future apply journal; callers must hold this context through the apply receipt."""

    def __init__(
        self, *, repository: pathlib.Path, journal_path: pathlib.Path, lease_path: pathlib.Path,
        operation_id: str, integrated_commit: str,
    ) -> None:
        if not DIGEST_RE.fullmatch(operation_id) or not COMMIT_RE.fullmatch(integrated_commit):
            refuse("journal operation or integrated commit is invalid")
        self.repository = repository.resolve()
        self.journal_path = assert_outside_repository(journal_path, repository, "operation journal")
        self.lease_path = assert_outside_repository(lease_path, repository, "operation lease")
        if (
            self.journal_path.parent != self.lease_path.parent
            or self.journal_path.parent.name != "phase6-resize-control"
            or self.journal_path.name != f"phase6-resize-operation-{operation_id}.json"
            or self.lease_path.name != "phase6-resize-operation.lock"
        ):
            refuse("journal and lease must use the canonical dedicated external control paths")
        assert_no_link_path(self.journal_path.parent, "operation journal directory")
        assert_no_link_path(self.journal_path, "operation journal", single_identity=True)
        assert_no_link_path(self.lease_path, "operation lease", single_identity=True)
        if self.journal_path.exists() and self.lease_path.exists():
            try:
                if os.path.samefile(self.journal_path, self.lease_path):
                    refuse("operation journal and lease share one file identity")
            except OSError:
                refuse("operation journal/lease file identity cannot be verified")
        self.operation_id = operation_id
        self.integrated_commit = integrated_commit
        self.lease: ExclusiveLease | None = None

    def __enter__(self) -> "OperationJournal":
        self.lease = ExclusiveLease(self.lease_path, self.operation_id)
        self.lease.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.lease is not None:
            self.lease.__exit__(exc_type, exc, traceback)
            self.lease = None

    def _held(self) -> None:
        if self.lease is None or self.lease.handle is None:
            refuse("operation journal transition requires the held canonical OS lease")

    def read(self) -> dict[str, Any] | None:
        self._held()
        if not self.journal_path.exists():
            return None
        journal = read_json(self.journal_path)
        exact_keys(
            journal,
            {
                "schema_version", "phase", "integrated_commit", "operation_id", "generation", "state",
                "node", "direction", "plan_sha256", "review_sha256", "prepare_sha256",
                "state_lineage_sha256", "state_serial_before", "apply_receipt_sha256",
                "created_at", "apply_started_at", "adopted_at", "completed_at",
            },
            "operation journal",
        )
        if (
            journal["schema_version"] != 1 or journal["phase"] != 6
            or journal["integrated_commit"] != self.integrated_commit
            or journal["operation_id"] != self.operation_id
            or not isinstance(journal["generation"], int) or journal["generation"] < 1
            or journal["state"] not in {"PREPARED", "APPLYING", "APPLIED"}
        ):
            refuse("operation journal identity or state is invalid")
        return journal

    def _cas(self, expected_generation: int, journal: dict[str, Any]) -> dict[str, Any]:
        current = self.read()
        actual = 0 if current is None else current["generation"]
        if actual != expected_generation:
            refuse("operation journal generation changed; compare-and-swap refused")
        journal["generation"] = expected_generation + 1
        write_json_atomic(self.journal_path, journal)
        return journal

    def prepare(
        self, *, expected_generation: int, node: str, direction: str, plan_sha256: str,
        review_sha256: str, prepare_sha256: str, state_lineage_sha256: str,
        state_serial_before: int, captured_at: str,
    ) -> dict[str, Any]:
        if node not in {"01", "02", "03"} or direction not in {"resize", "rollback"}:
            refuse("prepared journal target is invalid")
        for digest in (plan_sha256, review_sha256, prepare_sha256, state_lineage_sha256):
            if not DIGEST_RE.fullmatch(digest):
                refuse("prepared journal binding digest is invalid")
        if state_serial_before < 0:
            refuse("prepared journal state serial is invalid")
        created = parse_time(captured_at, "journal.created_at").isoformat()
        return self._cas(expected_generation, {
            "schema_version": 1, "phase": 6, "integrated_commit": self.integrated_commit,
            "operation_id": self.operation_id, "generation": 0, "state": "PREPARED",
            "node": node, "direction": direction, "plan_sha256": plan_sha256,
            "review_sha256": review_sha256, "prepare_sha256": prepare_sha256,
            "state_lineage_sha256": state_lineage_sha256, "state_serial_before": state_serial_before,
            "apply_receipt_sha256": None, "created_at": created, "apply_started_at": None,
            "adopted_at": None, "completed_at": None,
        })

    def begin_apply(self, *, expected_generation: int, captured_at: str) -> dict[str, Any]:
        journal = self.read()
        if journal is None or journal["state"] != "PREPARED":
            refuse("apply requires an existing PREPARED journal")
        journal["state"] = "APPLYING"
        journal["apply_started_at"] = parse_time(captured_at, "journal.apply_started_at").isoformat()
        return self._cas(expected_generation, journal)

    def adopt_applying(
        self, *, expected_generation: int, plan_sha256: str, state_lineage_sha256: str,
        state_serial_before: int, captured_at: str,
    ) -> dict[str, Any]:
        journal = self.read()
        if (
            journal is None or journal["state"] != "APPLYING"
            or journal["plan_sha256"] != plan_sha256
            or journal["state_lineage_sha256"] != state_lineage_sha256
            or journal["state_serial_before"] != state_serial_before
            or journal["adopted_at"] is not None
        ):
            refuse("crash adoption does not match the exact APPLYING journal")
        journal["adopted_at"] = parse_time(captured_at, "journal.adopted_at").isoformat()
        return self._cas(expected_generation, journal)

    def record_apply_receipt(
        self, *, expected_generation: int, receipt_sha256: str, captured_at: str,
    ) -> dict[str, Any]:
        journal = self.read()
        if journal is None or journal["state"] != "APPLYING" or not DIGEST_RE.fullmatch(receipt_sha256):
            refuse("apply receipt requires the exact APPLYING journal and digest")
        journal["state"] = "APPLIED"
        journal["apply_receipt_sha256"] = receipt_sha256
        journal["completed_at"] = parse_time(captured_at, "journal.completed_at").isoformat()
        return self._cas(expected_generation, journal)


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


def assert_cost_receipt(
    receipt: dict[str, Any], contract: dict[str, Any], integrated_commit: str, now: dt.datetime,
) -> None:
    exact_keys(
        receipt,
        {
            "schema_version", "phase", "integrated_commit", "captured_at", "shape", "location",
            "on_demand_available", "price_per_instance_hour_usd", "project_balance_usd",
            "seven_day_envelope_usd", "raw_values_recorded",
        },
        "cost receipt",
    )
    cost = contract["cost"]
    captured = parse_time(receipt["captured_at"], "cost receipt captured_at")
    age = (now.astimezone(dt.timezone.utc) - captured).total_seconds()
    if age < -30 or age > contract["freshness_seconds"]:
        refuse("cost receipt is stale or from the future")
    if (
        receipt["schema_version"] != 1 or receipt["phase"] != 6
        or receipt["integrated_commit"] != integrated_commit
        or receipt["shape"] != "CPU.8V.32G" or receipt["location"] != "FIN-03"
        or receipt["on_demand_available"] is not True
        or receipt["price_per_instance_hour_usd"] != cost["target_price_per_instance_hour_usd"]
        or receipt["seven_day_envelope_usd"] > cost["approved_seven_day_envelope_usd"]
        or receipt["project_balance_usd"] < cost["minimum_balance_with_reserve_usd"]
        or receipt["raw_values_recorded"] is not False
    ):
        refuse("cost receipt violates the exact price, balance, envelope, or availability contract")


def assert_capacity_receipt(receipt: dict[str, Any], contract: dict[str, Any], integrated_commit: str) -> None:
    exact_keys(
        receipt,
        {
            "schema_version", "phase", "integrated_commit", "candidate_node_count",
            "minimum_observed_per_node_cpu_millicores", "minimum_observed_per_node_memory_bytes",
            "worst_two_allocatable_cpu_millicores", "worst_two_allocatable_memory_bytes",
            "projection_sha256", "raw_values_recorded",
        },
        "capacity receipt",
    )
    capacity = contract["capacity"]
    if (
        receipt["schema_version"] != 1 or receipt["phase"] != 6
        or receipt["integrated_commit"] != integrated_commit or receipt["candidate_node_count"] != 3
        or receipt["minimum_observed_per_node_cpu_millicores"] < capacity["minimum_per_node_cpu_millicores"]
        or receipt["minimum_observed_per_node_memory_bytes"] < capacity["minimum_per_node_memory_bytes"]
        or receipt["worst_two_allocatable_cpu_millicores"] < capacity["minimum_worst_two_cpu_millicores"]
        or receipt["worst_two_allocatable_memory_bytes"] < capacity["minimum_worst_two_memory_bytes"]
        or not DIGEST_RE.fullmatch(str(receipt["projection_sha256"]))
        or receipt["raw_values_recorded"] is not False
    ):
        refuse("capacity receipt does not meet exact per-node and worst-two projection thresholds")


def assert_measured_capacity(facts: dict[str, Any], contract: dict[str, Any]) -> None:
    capacity = contract["capacity"]
    required = {
        "minimum_observed_per_node_cpu_millicores": capacity["minimum_per_node_cpu_millicores"],
        "minimum_observed_per_node_memory_bytes": capacity["minimum_per_node_memory_bytes"],
        "worst_two_allocatable_cpu_millicores": capacity["minimum_worst_two_cpu_millicores"],
        "worst_two_allocatable_memory_bytes": capacity["minimum_worst_two_memory_bytes"],
    }
    if any(not isinstance(facts.get(key), int) or facts[key] < minimum for key, minimum in required.items()):
        refuse("trusted collector measurements do not meet per-node and worst-two capacity thresholds")


def assert_trusted_collector_report(
    report: dict[str, Any], *, repository: pathlib.Path, integrated_commit: str, operation_id: str,
    node: str, survivor: str, direction: str, stage: str, now: dt.datetime, freshness_seconds: int,
) -> dict[str, Any]:
    exact_keys(
        report,
        {
            "schema_version", "collector", "collector_sha256", "stage", "phase", "cluster",
            "integrated_commit", "operation_id", "node", "survivor_node", "direction", "captured_at",
            "facts", "facts_sha256", "command_fingerprints", "input_fingerprints",
        },
        "collector report",
    )
    collector_path = repository / "scripts" / "phase6" / "management-resize-collector.py"
    expected_collector = digest_file(collector_path)
    captured = parse_time(report["captured_at"], "collector captured_at")
    age = (now.astimezone(dt.timezone.utc) - captured).total_seconds()
    expected = {
        "schema_version": 1, "collector": "phase6-management-resize-v1", "collector_sha256": expected_collector,
        "stage": stage, "phase": 6, "cluster": "management", "integrated_commit": integrated_commit,
        "operation_id": operation_id, "node": node, "survivor_node": survivor, "direction": direction,
    }
    if any(report.get(key) != value for key, value in expected.items()) or age < -30 or age > freshness_seconds:
        refuse("collector report identity, provenance, or freshness differs from execution")
    facts = report["facts"]
    if not isinstance(facts, dict) or report["facts_sha256"] != canonical_digest(facts):
        refuse("collector report facts digest differs")
    fingerprints = report["command_fingerprints"]
    inputs = report["input_fingerprints"]
    if (
        not isinstance(fingerprints, list) or len(fingerprints) < 8
        or any(not DIGEST_RE.fullmatch(str(value)) for value in fingerprints)
        or not isinstance(inputs, dict) or set(inputs) != {"inventory_sha256", "host_trust_sha256"}
        or any(not DIGEST_RE.fullmatch(str(value)) for value in inputs.values())
    ):
        refuse("collector command or input provenance is incomplete")
    always = {
        "ready_nodes": 3, "etcd_members": 3, "etcd_healthy_members": 3, "etcd_quorum": True,
        "cilium_ready_nodes": 3, "cilium_connectivity": True, "longhorn_ready_nodes": 3,
        "longhorn_schedulable_nodes": 3, "longhorn_healthy_volumes": True,
        "longhorn_degraded_volumes": 0, "argocd_all_healthy_synced": True,
    }
    if any(facts.get(key) != value for key, value in always.items()):
        refuse("collector did not derive the exact healthy cluster boundary")
    if stage == "preflight" and (
        facts.get("selected_node_is_not_current_etcd_leader") is not True
        or facts.get("drain_server_dry_run") is not True
        or facts.get("etcd_off_cluster_snapshot_verified") is not True
        or facts.get("data_recovery_point_verified") is not True
    ):
        refuse("collector preflight safety facts are incomplete")
    return facts


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
    operation_id: str, plan_sha: str, plan_semantic_sha: str, gate_sha: str, contract_sha: str,
    cost_sha: str, capacity_sha: str, collector_sha: str, tool_lock_sha: str,
) -> None:
    exact_keys(
        review,
        {
            "schema_version", "phase", "integrated_commit", "node", "direction",
            "operation_id", "plan_sha256", "plan_semantic_sha256", "preflight_sha256",
            "contract_sha256", "cost_receipt_sha256", "capacity_receipt_sha256",
            "collector_report_sha256", "tool_lock_sha256", "author_digest",
            "reviewer_digest", "reliability_reviewer_digest", "security_approved",
            "capacity_approved", "reliability_approved",
        },
        "review",
    )
    expected = {
        "schema_version": 1,
        "phase": 6,
        "integrated_commit": integrated_commit,
        "node": node,
        "direction": direction,
        "operation_id": operation_id,
        "plan_sha256": plan_sha,
        "plan_semantic_sha256": plan_semantic_sha,
        "preflight_sha256": gate_sha,
        "contract_sha256": contract_sha,
        "cost_receipt_sha256": cost_sha,
        "capacity_receipt_sha256": capacity_sha,
        "collector_report_sha256": collector_sha,
        "tool_lock_sha256": tool_lock_sha,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            refuse(f"review {key} is not bound to this execution")
    for key in ("author_digest", "reviewer_digest", "reliability_reviewer_digest"):
        if not isinstance(review[key], str) or not DIGEST_RE.fullmatch(review[key]):
            refuse(f"review {key} must be an identity-free SHA-256 digest")
    if len({review["author_digest"], review["reviewer_digest"], review["reliability_reviewer_digest"]}) != 3:
        refuse("author, security reviewer, and reliability reviewer must be distinct")
    if any(review[key] is not True for key in ("security_approved", "capacity_approved", "reliability_approved")):
        refuse("security, capacity, and reliability reviews must approve the exact execution")


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
    cost_path: pathlib.Path, capacity_path: pathlib.Path, collector_path: pathlib.Path,
    operation_id: str, survivor: str, direction: str, git_commit: str, repository: pathlib.Path,
    now: dt.datetime | None = None, plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate legacy review fixtures only; this result never authorizes mutation."""
    now = now or dt.datetime.now(dt.timezone.utc)
    contract = read_json(contract_path)
    validate_contract(contract)
    integrated = require_activation(contract, git_commit)
    assert_clean_reviewed_worktree(repository, integrated)
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
    semantic_sha = canonical_digest(details)

    preflight = read_json(preflight_path)
    assert_gate_bundle(preflight, contract["required_preflight"], integrated, node, contract, now, "preflight")
    gate_sha = digest_file(preflight_path)
    cost = read_json(cost_path)
    assert_cost_receipt(cost, contract, integrated, now)
    cost_sha = digest_file(cost_path)
    capacity = read_json(capacity_path)
    assert_capacity_receipt(capacity, contract, integrated)
    capacity_sha = digest_file(capacity_path)
    collector = read_json(collector_path)
    collector_facts = assert_trusted_collector_report(
        collector, repository=repository, integrated_commit=integrated, operation_id=operation_id,
        node=node, survivor=survivor, direction=direction, stage="preflight", now=now,
        freshness_seconds=contract["freshness_seconds"],
    )
    assert_measured_capacity(collector_facts, contract)
    collector_sha = digest_file(collector_path)
    tool_lock_sha = canonical_digest({
        "versions_lock": digest_file(repository / "versions.lock.yaml"),
        "terraform_lock": digest_file(
            repository / "infra" / "terraform" / "environments" / "management" / ".terraform.lock.hcl"
        ),
        "controller": digest_file(repository / "scripts" / "phase6" / "management-node-resize.py"),
        "collector": digest_file(repository / "scripts" / "phase6" / "management-resize-collector.py"),
        "prepare_playbook": digest_file(
            repository / "infra" / "ansible" / "playbooks" / "prepare-management-node-resize.yml"
        ),
        "recovery_playbook": digest_file(
            repository / "infra" / "ansible" / "playbooks" / "recover-resized-management-node.yml"
        ),
        "prepare_helper": digest_file(repository / "scripts" / "phase6" / "prepare-management-node-resize.sh"),
        "management_group_vars": digest_file(
            repository / "infra" / "ansible" / "inventories" / "group_vars" / "management_servers.yml"
        ),
    })
    lease = read_json(lease_path)
    assert_lease(lease, integrated, now)
    review = read_json(review_path)
    assert_review(
        review, integrated, node, direction, operation_id, plan_sha, semantic_sha, gate_sha, contract_sha,
        cost_sha, capacity_sha, collector_sha, tool_lock_sha,
    )

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
        "plan_semantic_sha256": semantic_sha,
        "preflight_sha256": gate_sha,
        "cost_receipt_sha256": cost_sha,
        "capacity_receipt_sha256": capacity_sha,
        "collector_report_sha256": collector_sha,
        "tool_lock_sha256": tool_lock_sha,
        "contract_sha256": contract_sha,
        "reviewer_count": 3,
        "all_preflight_gates_passed": True,
    }


def verify_postflight(
    contract_path: pathlib.Path, postflight_path: pathlib.Path, node: str,
    git_commit: str, now: dt.datetime | None = None,
) -> dict[str, Any]:
    refuse(
        "postflight advancement is disabled; reviewed collector and journal components have no activation route"
    )


def recovery_admission(
    *, contract_path: pathlib.Path, progress_path: pathlib.Path, recovery_path: pathlib.Path,
    lease_path: pathlib.Path, direction: str, git_commit: str, repository: pathlib.Path,
    inventory_path: pathlib.Path, private_key_path: pathlib.Path, known_hosts_path: pathlib.Path,
    runtime_vars_path: pathlib.Path, now: dt.datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    refuse(
        "host recovery is disabled; the pinned container runner and trusted collector are review-only"
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
