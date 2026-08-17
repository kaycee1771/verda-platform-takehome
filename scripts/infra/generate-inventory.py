#!/usr/bin/env python3
"""Render deterministic ignored Ansible inventory from Terraform outputs."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--private-key", required=True, type=pathlib.Path)
    args = parser.parse_args()

    command = [
        "terraform",
        f"-chdir={args.root.resolve()}",
        "output",
        "-json",
        "ansible_inventory",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print("[FAIL] Unable to read Terraform inventory output.", file=sys.stderr)
        return 1
    inventory = json.loads(result.stdout)
    hosts = inventory["all"]["children"]["management_servers"]["hosts"]
    if sorted(hosts) != [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]:
        print("[FAIL] Terraform inventory does not contain the exact Stage A nodes.", file=sys.stderr)
        return 1
    if not args.private_key.is_file():
        print("[FAIL] Dedicated SSH private key is missing.", file=sys.stderr)
        return 1
    for host in hosts.values():
        host["ansible_ssh_private_key_file"] = str(args.private_key.resolve())
        host["ansible_ssh_common_args"] = "-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = "---\n" + yaml.safe_dump(inventory, sort_keys=True, default_flow_style=False)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"[PASS] Generated ignored inventory for {len(hosts)} management nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
