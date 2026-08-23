#!/usr/bin/env python3
"""Generate a strict, external inventory after one Terraform replacement."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml


NODES = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = child
    return value


def outside(path: pathlib.Path, repository: pathlib.Path, label: str) -> pathlib.Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(repository.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"{label} must remain outside the repository")


def validate_inventory(inventory: object, known_hosts: pathlib.Path) -> dict[str, dict[str, object]]:
    try:
        hosts = inventory["all"]["children"]["management_servers"]["hosts"]  # type: ignore[index]
    except (KeyError, TypeError) as error:
        raise ValueError("invalid management inventory topology") from error
    if not isinstance(hosts, dict) or sorted(hosts) != NODES:
        raise ValueError("management inventory differs from the exact three-node topology")
    expected_fields = {
        "ansible_host", "ansible_user", "node_name", "role", "internal_ip", "wireguard_ip",
        "data_volume_id", "attached_device_id", "data_volume_size_gib",
    }
    public_addresses: list[str] = []
    for name, host in hosts.items():
        if not isinstance(host, dict) or set(host) != expected_fields:
            raise ValueError("inventory host fields differ from the canonical output schema")
        if host["node_name"] != name or host["ansible_user"] != "root":
            raise ValueError("inventory hostname or SSH user differs from contract")
        if host["data_volume_size_gib"] != 100 or host["data_volume_id"] != host["attached_device_id"]:
            raise ValueError("persistent volume size or attachment continuity differs from contract")
        public_addresses.append(str(host["ansible_host"]))
    if len(set(public_addresses)) != 3:
        raise ValueError("inventory public endpoints are not unique")
    for address in public_addresses:
        lookup = subprocess.run(
            ["ssh-keygen", "-F", address, "-f", str(known_hosts)],
            check=False, capture_output=True,
        )
        if lookup.returncode != 0:
            raise ValueError("known-hosts provenance is incomplete for the canonical inventory")
    return hosts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=pathlib.Path, required=True)
    parser.add_argument("--terraform-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--private-key", type=pathlib.Path, required=True)
    parser.add_argument("--known-hosts", type=pathlib.Path, required=True)
    args = parser.parse_args()

    try:
        output = outside(args.output, args.repository, "inventory")
        private_key = outside(args.private_key, args.repository, "private key")
        known_hosts = outside(args.known_hosts, args.repository, "known-hosts file")
    except ValueError as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 64
    if not private_key.is_file() or not known_hosts.is_file():
        print("[FAIL] Strict SSH identity inputs are absent.", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["terraform", f"-chdir={args.terraform_root.resolve()}", "output", "-json", "ansible_inventory"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("[FAIL] Unable to read the post-replacement Terraform inventory; raw diagnostic withheld.", file=sys.stderr)
        return 1
    try:
        inventory = json.loads(result.stdout, object_pairs_hook=unique_object)
        hosts = validate_inventory(inventory, known_hosts)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        print("[FAIL] Terraform returned an invalid management inventory; raw data withheld.", file=sys.stderr)
        return 1
    common = (
        "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
        f"-o UserKnownHostsFile={known_hosts}"
    )
    for host in hosts.values():
        host["ansible_ssh_private_key_file"] = str(private_key)
        host["ansible_ssh_common_args"] = common

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("---\n" + yaml.safe_dump(inventory, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print("[PASS] Strict external inventory refreshed for exactly three management nodes; identities withheld.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
