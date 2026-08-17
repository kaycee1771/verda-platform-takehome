#!/usr/bin/env python3
"""Build ignored strict-SSH Phase 3 inventories without leaking endpoint data."""

from __future__ import annotations

import argparse
import ipaddress
import json
import pathlib
import sys

import yaml


EXPECTED_HOSTS = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]
WIREGUARD_ADDRESSES = {
    host: f"10.250.0.{index + 10}" for index, host in enumerate(EXPECTED_HOSTS, 1)
}


def fail(message: str) -> None:
    raise ValueError(message)


def validate_cidrs(raw: str) -> list[str]:
    cidrs: list[str] = []
    for value in (item.strip() for item in raw.split(",")):
        if not value:
            continue
        network = ipaddress.ip_network(value, strict=False)
        if network.version != 4:
            fail("Phase 3 currently accepts only approved IPv4 administrative CIDRs")
        if str(network) != value:
            fail("administrative CIDRs must be canonical network values")
        cidrs.append(value)
    if not cidrs:
        fail("at least one approved administrative CIDR is required")
    return sorted(set(cidrs))


def build_runtime(
    source: dict[str, object], user: str, private_key: str, known_hosts: str
) -> dict[str, object]:
    try:
        hosts = source["all"]["children"]["management_servers"]["hosts"]
    except (KeyError, TypeError) as error:
        fail(f"generated inventory structure is invalid: {error}")
    if sorted(hosts) != EXPECTED_HOSTS:
        fail("generated inventory does not contain the exact management hosts")

    endpoints: set[str] = set()
    for name in EXPECTED_HOSTS:
        host = hosts[name]
        endpoint = str(host.get("ansible_host", ""))
        ipaddress.ip_address(endpoint)
        endpoints.add(endpoint)
        if host.get("data_volume_size_gib") != 100:
            fail(f"{name} does not have the expected 100 GiB data-volume contract")
        if host.get("data_volume_id") != host.get("attached_device_id"):
            fail(f"{name} attachment identity differs from the data-volume identity")
        host["ansible_user"] = user
        host["ansible_ssh_private_key_file"] = private_key
        host["ansible_ssh_common_args"] = (
            "-o BatchMode=yes -o IdentitiesOnly=yes "
            "-o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={known_hosts} -o ConnectTimeout=10"
        )
        host["wireguard_ip"] = WIREGUARD_ADDRESSES[name]
    if len(endpoints) != 3:
        fail("management endpoints are not unique")
    return source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=pathlib.Path)
    parser.add_argument("--root-output", required=True, type=pathlib.Path)
    parser.add_argument("--admin-output", required=True, type=pathlib.Path)
    parser.add_argument("--vars-output", required=True, type=pathlib.Path)
    parser.add_argument("--metadata-output", required=True, type=pathlib.Path)
    parser.add_argument("--admin-cidrs", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source = yaml.safe_load(args.inventory.read_text(encoding="utf-8"))
        cidrs = validate_cidrs(args.admin_cidrs)
        root_inventory = build_runtime(
            json.loads(json.dumps(source)),
            "root",
            "/tmp/phase3-ssh-key",
            "/run/config/known_hosts",
        )
        admin_inventory = build_runtime(
            json.loads(json.dumps(source)),
            "platform-admin",
            "/tmp/phase3-ssh-key",
            "/run/config/known_hosts",
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[FAIL] Phase 3 runtime preparation: {error}", file=sys.stderr)
        return 1

    for output, inventory in (
        (args.root_output, root_inventory),
        (args.admin_output, admin_inventory),
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "---\n" + yaml.safe_dump(inventory, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
    args.vars_output.write_text(
        json.dumps({"phase3_admin_cidrs_v4": cidrs}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    hosts = admin_inventory["all"]["children"]["management_servers"]["hosts"]
    args.metadata_output.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "name": name,
                        "public_address": hosts[name]["ansible_host"],
                        "wireguard_address": WIREGUARD_ADDRESSES[name],
                    }
                    for name in EXPECTED_HOSTS
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("[PASS] Prepared strict ignored Phase 3 runtime for exactly three hosts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
