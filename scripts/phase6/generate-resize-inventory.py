#!/usr/bin/env python3
"""Generate a strict, external inventory after one Terraform replacement."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import yaml


def outside(path: pathlib.Path, repository: pathlib.Path, label: str) -> pathlib.Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(repository.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"{label} must remain outside the repository")


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
        inventory = json.loads(result.stdout)
        hosts = inventory["all"]["children"]["management_servers"]["hosts"]
    except (json.JSONDecodeError, KeyError, TypeError):
        print("[FAIL] Terraform returned an invalid management inventory; raw data withheld.", file=sys.stderr)
        return 1
    expected = [f"verda-mgmt-server-{index:02d}" for index in range(1, 4)]
    if sorted(hosts) != expected:
        print("[FAIL] Post-replacement inventory differs from the exact three-node topology.", file=sys.stderr)
        return 1
    common = (
        "-o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
        f"-o UserKnownHostsFile={known_hosts}"
    )
    for host in hosts.values():
        host["ansible_ssh_private_key_file"] = str(private_key)
        host["ansible_ssh_common_args"] = common

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("---\n" + yaml.safe_dump(inventory, sort_keys=True), encoding="utf-8", newline="\n")
    print("[PASS] Strict external inventory refreshed for exactly three management nodes; identities withheld.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
