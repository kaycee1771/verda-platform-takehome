#!/usr/bin/env python3
"""Fail-closed verifier for Phase 6 Ansible/helper operation authorization."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys


DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def refuse(message: str) -> None:
    raise ValueError(message)


def read(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        refuse("authorization input is not one JSON object")
    return value


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str):
        refuse("authorization expiry is invalid")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        refuse("authorization expiry lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=pathlib.Path, required=True)
    parser.add_argument("--contract", type=pathlib.Path, required=True)
    parser.add_argument("--journal", type=pathlib.Path, required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--node", choices=("01", "02", "03"), required=True)
    parser.add_argument("--direction", choices=("resize", "rollback"), required=True)
    parser.add_argument("--mode", choices=("prepare", "recover"), required=True)
    args = parser.parse_args()
    try:
        if not DIGEST.fullmatch(args.authorization_sha256) or not DIGEST.fullmatch(args.operation_id):
            refuse("authorization digest or operation ID is invalid")
        if not COMMIT.fullmatch(args.commit):
            refuse("authorization commit is invalid")
        if digest(args.authorization) != args.authorization_sha256:
            refuse("authorization file digest differs")
        authorization, contract, journal = read(args.authorization), read(args.contract), read(args.journal)
        expected_keys = {
            "schema_version", "phase", "status", "integrated_commit", "operation_id", "node",
            "direction", "mode", "contract_sha256", "journal_sha256", "expires_at",
            "raw_values_recorded",
        }
        if set(authorization) != expected_keys:
            refuse("authorization schema differs")
        expected = {
            "schema_version": 1, "phase": 6, "status": "CONTROLLER_OPERATION_AUTHORIZED",
            "integrated_commit": args.commit, "operation_id": args.operation_id,
            "node": args.node, "direction": args.direction, "mode": args.mode,
            "contract_sha256": digest(args.contract), "journal_sha256": digest(args.journal),
            "raw_values_recorded": False,
        }
        if any(authorization.get(key) != value for key, value in expected.items()):
            refuse("authorization identity or hash binding differs")
        now = dt.datetime.now(dt.timezone.utc)
        expiry = timestamp(authorization["expires_at"])
        if expiry <= now or (expiry - now).total_seconds() > 600:
            refuse("authorization is expired or exceeds the ten-minute boundary")
        activation = contract.get("activation", {})
        if (
            contract.get("phase") != 6 or contract.get("cluster") != "management"
            or activation.get("enabled") is not True or activation.get("writes_allowed") is not True
            or activation.get("integrated_commit") != args.commit
            or contract.get("terraform", {}).get("target_resource_expiry_utc") != "2026-08-27T21:00:00Z"
        ):
            refuse("active external contract is not the exact approved Phase 6 boundary")
        expected_state = "PREPARED" if args.mode == "prepare" else "APPLIED"
        if (
            journal.get("schema_version") != 1 or journal.get("phase") != 6
            or journal.get("integrated_commit") != args.commit
            or journal.get("operation_id") != args.operation_id
            or journal.get("node") != args.node or journal.get("direction") != args.direction
            or journal.get("state") != expected_state
        ):
            refuse("operation journal is not in the exact authorized state")
        print('{"schema_version":1,"status":"AUTHORIZED"}')
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
