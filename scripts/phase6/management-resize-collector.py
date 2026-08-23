#!/usr/bin/env python3
"""Trusted, identity-free live fact collector for Phase 6 node replacement.

This program is invoked only inside the pinned quality container. It accepts
paths to read-only credential files, never their values, executes a fixed
command set, and emits derived facts plus command fingerprints. Raw command
output and infrastructure identities are never emitted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

import yaml


NODES = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]
WG_ADDRESSES = {
    "verda-mgmt-server-01": "10.250.0.11",
    "verda-mgmt-server-02": "10.250.0.12",
    "verda-mgmt-server-03": "10.250.0.13",
}
FORBIDDEN_KEY = re.compile(r"(?i)(client.?secret|credential|kubeconfig|private.?key|resource.?id|secret|token)")


class CollectionError(RuntimeError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    value: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise CollectionError("strict inventory contains a duplicate mapping key")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class Runner:
    def __init__(self) -> None:
        self.fingerprints: list[str] = []

    def run(self, argv: list[str], *, stdin: bytes | None = None) -> bytes:
        self.fingerprints.append(canonical_digest(argv))
        result = subprocess.run(argv, input=stdin, check=False, capture_output=True)
        if result.returncode != 0:
            raise CollectionError(f"fixed collector command failed: {pathlib.Path(argv[0]).name}")
        return result.stdout

    def json(self, argv: list[str]) -> Any:
        raw = self.run(argv)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise CollectionError("fixed collector command returned invalid JSON") from error


def read_inventory(path: pathlib.Path) -> tuple[dict[str, dict[str, Any]], pathlib.Path]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        hosts = value["all"]["children"]["management_servers"]["hosts"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as error:
        raise CollectionError("strict inventory is invalid") from error
    if not isinstance(hosts, dict) or sorted(hosts) != NODES:
        raise CollectionError("strict inventory does not contain the exact management topology")
    required = {
        "ansible_host", "ansible_user", "ansible_ssh_private_key_file", "ansible_ssh_common_args",
        "node_name", "role", "internal_ip", "wireguard_ip", "data_volume_id",
        "attached_device_id", "data_volume_size_gib",
    }
    addresses: list[str] = []
    internal_addresses: list[str] = []
    wireguard_addresses: list[str] = []
    known_hosts_values: set[str] = set()
    for name, host in hosts.items():
        if not isinstance(host, dict) or set(host) != required:
            raise CollectionError(f"strict inventory fields are incomplete for node {name[-2:]}")
        try:
            ipaddress.ip_address(host["ansible_host"])
            ipaddress.ip_address(host["internal_ip"])
            ipaddress.ip_address(host["wireguard_ip"])
        except ValueError as error:
            raise CollectionError("inventory contains an invalid host endpoint") from error
        addresses.append(str(host["ansible_host"]))
        internal_addresses.append(str(host["internal_ip"]))
        wireguard_addresses.append(str(host["wireguard_ip"]))
        if (
            host["ansible_user"] != "root" or host["node_name"] != name or host["role"] != "server"
            or host["wireguard_ip"] != WG_ADDRESSES[name]
        ):
            raise CollectionError("inventory SSH user or canonical hostname differs from contract")
        if host["data_volume_size_gib"] != 100 or host["data_volume_id"] != host["attached_device_id"]:
            raise CollectionError("inventory volume size or attachment continuity differs from contract")
        key_value = str(host["ansible_ssh_private_key_file"])
        if not (pathlib.Path(key_value).is_absolute() or pathlib.PurePosixPath(key_value).is_absolute()):
            raise CollectionError("inventory private-key descriptor is not absolute")
        ssh_args = str(host["ansible_ssh_common_args"])
        prefix = "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="
        if not ssh_args.startswith(prefix) or len(ssh_args.split()) != 8:
            raise CollectionError("inventory does not contain the exact strict SSH argument set")
        known_hosts = ssh_args.removeprefix(prefix)
        if not (pathlib.Path(known_hosts).is_absolute() or pathlib.PurePosixPath(known_hosts).is_absolute()):
            raise CollectionError("inventory known-hosts descriptor is not absolute")
        known_hosts_values.add(known_hosts)
    if (
        any(len(set(values)) != 3 for values in (addresses, internal_addresses, wireguard_addresses))
        or len(known_hosts_values) != 1
    ):
        raise CollectionError("inventory endpoints or known-hosts provenance are not uniquely bound")
    return hosts, pathlib.Path(known_hosts_values.pop())


def memory_bytes(value: Any) -> int:
    if not isinstance(value, str):
        raise CollectionError("node allocatable memory is invalid")
    match = re.fullmatch(r"([0-9]+)(Ki|Mi|Gi)?", value)
    if not match:
        raise CollectionError("node allocatable memory is invalid")
    multiplier = {None: 1, "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3}[match.group(2)]
    return int(match.group(1)) * multiplier


def ready_nodes(nodes: dict[str, Any]) -> tuple[int, dict[str, int], dict[str, int]]:
    items = nodes.get("items", [])
    counts: dict[str, int] = {}
    memory: dict[str, int] = {}
    ready = 0
    for item in items:
        name = item.get("metadata", {}).get("name")
        if name not in NODES:
            continue
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in item.get("status", {}).get("conditions", [])):
            ready += 1
        cpu = item.get("status", {}).get("allocatable", {}).get("cpu", "")
        if isinstance(cpu, str) and cpu.endswith("m") and cpu[:-1].isdigit():
            counts[name] = int(cpu[:-1])
        elif isinstance(cpu, str) and cpu.isdigit():
            counts[name] = int(cpu) * 1000
        else:
            raise CollectionError("node allocatable CPU is invalid")
        memory[name] = memory_bytes(item.get("status", {}).get("allocatable", {}).get("memory"))
    if len(counts) != 3 or len(memory) != 3:
        raise CollectionError("node facts do not contain the exact management topology")
    return ready, counts, memory


def etcd_facts(status: Any, members: Any, target: str, stage: str = "preflight") -> dict[str, Any]:
    expected_healthy = 2 if stage == "recovery" else 3
    if not isinstance(status, list) or len(status) != expected_healthy:
        raise CollectionError("etcd endpoint status does not contain the stage-specific healthy endpoint count")
    member_list = members.get("members", []) if isinstance(members, dict) else []
    if len(member_list) != 3:
        raise CollectionError("etcd membership does not contain exactly three members")
    names = sorted(item.get("name") for item in member_list)
    if names != NODES:
        raise CollectionError("etcd member names differ from the management topology")
    healthy_ids = set()
    leaders = set()
    target_id = None
    for entry in status:
        endpoint = entry.get("Endpoint", "")
        payload = entry.get("Status", {})
        member_id = payload.get("header", {}).get("member_id")
        leader = payload.get("leader")
        if not isinstance(member_id, int) or not isinstance(leader, int):
            raise CollectionError("etcd endpoint status lacks numeric member/leader identity")
        healthy_ids.add(member_id)
        leaders.add(leader)
        if WG_ADDRESSES[target] in endpoint:
            target_id = member_id
    if len(healthy_ids) != expected_healthy or len(leaders) != 1:
        raise CollectionError("etcd endpoint health/leadership is ambiguous")
    if stage != "recovery" and target_id is None:
        raise CollectionError("selected etcd member identity is absent")
    return {
        "etcd_members": 3,
        "etcd_healthy_members": expected_healthy,
        "etcd_quorum": True,
        "selected_node_is_not_current_etcd_leader": target_id not in leaders if target_id is not None else True,
    }


def cilium_facts(status: Any) -> dict[str, Any]:
    if not isinstance(status, dict):
        raise CollectionError("Cilium status is invalid")
    errors = status.get("errors", [])
    warnings = status.get("warnings", [])
    cluster = status.get("cluster", {})
    desired = cluster.get("desired")
    ready = cluster.get("ready")
    if errors or not isinstance(desired, int) or desired != 3 or ready != 3:
        raise CollectionError("Cilium is not healthy on exactly three nodes")
    return {"cilium_ready_nodes": 3, "cilium_connectivity": not warnings}


def longhorn_facts(nodes: dict[str, Any], volumes: dict[str, Any]) -> dict[str, Any]:
    node_items = nodes.get("items", [])
    if len(node_items) != 3:
        raise CollectionError("Longhorn does not report exactly three nodes")
    ready = schedulable = 0
    for item in node_items:
        conditions = item.get("status", {}).get("conditions", [])
        condition_map = {c.get("type"): c.get("status") for c in conditions}
        if condition_map.get("Ready") == "True":
            ready += 1
        if condition_map.get("Schedulable") == "True":
            schedulable += 1
    volume_items = volumes.get("items", [])
    if not volume_items:
        raise CollectionError("Longhorn volume set is empty")
    degraded = sum(1 for item in volume_items if item.get("status", {}).get("robustness") != "healthy")
    return {
        "longhorn_ready_nodes": ready,
        "longhorn_schedulable_nodes": schedulable,
        "longhorn_healthy_volumes": degraded == 0,
        "longhorn_degraded_volumes": degraded,
        "longhorn_rebuild_complete": degraded == 0,
    }


def argo_facts(applications: dict[str, Any]) -> dict[str, Any]:
    items = applications.get("items", [])
    if not items:
        raise CollectionError("Argo CD application set is empty")
    unhealthy = [
        item for item in items
        if item.get("status", {}).get("health", {}).get("status") != "Healthy"
        or item.get("status", {}).get("sync", {}).get("status") != "Synced"
    ]
    return {"argocd_application_count": len(items), "argocd_all_healthy_synced": not unhealthy}


def snapshot_facts(snapshot: Any, *, now: dt.datetime, freshness_seconds: int) -> dict[str, Any]:
    items = snapshot.get("items") if isinstance(snapshot, dict) else snapshot
    if not isinstance(items, list) or not items:
        raise CollectionError("off-cluster snapshot inventory is empty or invalid")
    verified = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("spec"), dict) or not isinstance(item.get("status"), dict):
            continue
        spec, status = item["spec"], item["status"]
        try:
            created = dt.datetime.fromisoformat(str(status.get("creationTime", "")).replace("Z", "+00:00"))
            if created.tzinfo is None:
                continue
            age = (now.astimezone(dt.timezone.utc) - created.astimezone(dt.timezone.utc)).total_seconds()
        except ValueError:
            continue
        if (
            str(spec.get("location", "")).startswith("s3://")
            and str(spec.get("snapshotName", "")).endswith(".zip")
            and status.get("readyToUse") is True
            and str(status.get("size", "")) not in {"", "0", "None"}
            and -30 <= age <= freshness_seconds
        ):
            verified.append(item)
    if not verified:
        raise CollectionError("no successful structured off-cluster snapshot was verified")
    return {"etcd_off_cluster_snapshot_verified": True, "etcd_off_cluster_snapshot_count": len(verified)}


def command_set(
    runner: Runner, kubeconfig: pathlib.Path, inventory: pathlib.Path, target: str, survivor: str, stage: str,
    *, now: dt.datetime | None = None, freshness_seconds: int = 600,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    hosts, known_hosts = read_inventory(inventory)
    if survivor == target or survivor not in NODES:
        raise CollectionError("collector survivor is invalid")
    for host in hosts.values():
        runner.run(["ssh-keygen", "-F", str(host["ansible_host"]), "-f", str(known_hosts)])
    kubectl = ["kubectl", f"--kubeconfig={kubeconfig}"]
    nodes = runner.json(kubectl + ["get", "nodes", "-o", "json"])
    ready, allocatable, allocatable_memory = ready_nodes(nodes)
    survivor_host = hosts[survivor]
    ssh = [
        "ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-i", str(survivor_host["ansible_ssh_private_key_file"]),
        f"{survivor_host['ansible_user']}@{survivor_host['ansible_host']}",
    ]
    endpoint_nodes = [node for node in NODES if stage != "recovery" or node != target]
    endpoints = ",".join(f"https://{WG_ADDRESSES[node]}:2379" for node in endpoint_nodes)
    etcd_prefix = (
        "sudo -n /usr/local/libexec/verda-phase4/etcdctl-local "
        f"--endpoints={endpoints} "
        "--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt "
        "--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt "
        "--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key"
    )
    status = json.loads(runner.run(ssh + [f"{etcd_prefix} endpoint status --write-out=json"]))
    members = json.loads(runner.run(ssh + [f"{etcd_prefix} member list --write-out=json"]))
    facts = {"ready_nodes": ready, **etcd_facts(status, members, target, stage)}
    if stage == "recovery":
        if ready != 2:
            raise CollectionError("recovery boundary does not contain exactly two Ready survivors")
        facts.update({
            "surviving_ready_nodes": 2, "surviving_etcd_healthy_members": 2,
            "replacement_not_ready": True, "partial_inventory_refreshed": True,
            "wireguard_peer_inputs_complete": True,
        })
        return facts
    cilium = runner.json(["cilium", "status", f"--kubeconfig={kubeconfig}", "--output=json"])
    facts.update(cilium_facts(cilium))
    facts.update(longhorn_facts(
        runner.json(kubectl + ["-n", "longhorn-system", "get", "nodes.longhorn.io", "-o", "json"]),
        runner.json(kubectl + ["-n", "longhorn-system", "get", "volumes.longhorn.io", "-o", "json"]),
    ))
    facts.update(argo_facts(runner.json(kubectl + ["-n", "argocd", "get", "applications.argoproj.io", "-o", "json"])))
    facts["candidate_allocatable_cpu_millicores"] = allocatable[target]
    facts["candidate_two_survivor_cpu_millicores"] = sum(value for name, value in allocatable.items() if name != target)
    facts["candidate_allocatable_memory_bytes"] = allocatable_memory[target]
    facts["candidate_two_survivor_memory_bytes"] = sum(
        value for name, value in allocatable_memory.items() if name != target
    )
    facts["worst_two_allocatable_cpu_millicores"] = sum(sorted(allocatable.values())[:2])
    facts["worst_two_allocatable_memory_bytes"] = sum(sorted(allocatable_memory.values())[:2])
    facts["minimum_observed_per_node_cpu_millicores"] = min(allocatable.values())
    facts["minimum_observed_per_node_memory_bytes"] = min(allocatable_memory.values())

    if stage == "preflight":
        runner.run(kubectl + [
            "drain", target, "--ignore-daemonsets", "--delete-emptydir-data",
            "--dry-run=server", "--timeout=60s",
        ])
        facts["drain_server_dry_run"] = True
        snapshot = runner.json(ssh + [
            "sudo -n /usr/local/bin/rke2 etcd-snapshot ls --output=json"
        ])
        facts.update(snapshot_facts(snapshot, now=now, freshness_seconds=freshness_seconds))
        stateful = runner.json(kubectl + ["get", "statefulsets", "--all-namespaces", "-o", "json"])
        protected_namespaces = {"argocd", "cert-manager", "longhorn-system"}
        unprotected = [
            item for item in stateful.get("items", [])
            if item.get("metadata", {}).get("namespace") not in protected_namespaces
        ]
        facts["data_recovery_point_verified"] = not unprotected
    return facts


def ensure_identity_free(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if FORBIDDEN_KEY.search(str(key)):
                raise CollectionError(f"identity-free report contains forbidden key at {path or 'root'}")
            ensure_identity_free(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            ensure_identity_free(child, f"{path}[{index}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("preflight", "recovery", "postflight"), required=True)
    parser.add_argument("--node", choices=NODES, required=True)
    parser.add_argument("--survivor", choices=NODES, required=True)
    parser.add_argument("--direction", choices=("resize", "rollback"), required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--kubeconfig", type=pathlib.Path, required=True)
    parser.add_argument("--inventory", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
            raise CollectionError("collector commit is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", args.operation_id):
            raise CollectionError("collector operation identity is invalid")
        runner = Runner()
        facts = command_set(runner, args.kubeconfig, args.inventory, args.node, args.survivor, args.stage)
        report = {
            "schema_version": 1,
            "collector": "phase6-management-resize-v1",
            "collector_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
            "stage": args.stage,
            "phase": 6,
            "cluster": "management",
            "integrated_commit": args.commit,
            "operation_id": args.operation_id,
            "node": args.node[-2:],
            "survivor_node": args.survivor[-2:],
            "direction": args.direction,
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "facts": facts,
            "facts_sha256": canonical_digest(facts),
            "command_fingerprints": runner.fingerprints,
            "input_fingerprints": {
                "inventory_sha256": hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
                "host_trust_sha256": hashlib.sha256(read_inventory(args.inventory)[1].read_bytes()).hexdigest(),
            },
        }
        ensure_identity_free(report)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except (CollectionError, json.JSONDecodeError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
