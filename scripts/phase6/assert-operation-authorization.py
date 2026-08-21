#!/usr/bin/env python3
"""Fail-closed verifier for Phase 6 Ansible/helper operation authorization."""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
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


def dpapi_unprotect(path: pathlib.Path) -> bytes:
    if os.name != "nt":
        refuse("apply capability DPAPI verification requires Windows")

    class DataBlob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    encrypted = path.read_bytes()
    encrypted_buffer = ctypes.create_string_buffer(encrypted)
    source = DataBlob(len(encrypted), ctypes.cast(encrypted_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    plaintext = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(plaintext)
    ):
        refuse("apply capability secret cannot be DPAPI-unsealed")
    try:
        return ctypes.string_at(plaintext.data, plaintext.size)
    finally:
        ctypes.windll.kernel32.LocalFree(plaintext.data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=pathlib.Path, required=True)
    parser.add_argument("--capability-secret", type=pathlib.Path)
    parser.add_argument("--contract", type=pathlib.Path, required=True)
    parser.add_argument("--journal", type=pathlib.Path, required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--node", choices=("01", "02", "03"), required=True)
    parser.add_argument("--direction", choices=("resize", "rollback"), required=True)
    parser.add_argument("--mode", choices=("prepare", "apply", "recover"), required=True)
    parser.add_argument("--repository", type=pathlib.Path)
    parser.add_argument("--journal-generation", type=int, default=-1)
    parser.add_argument("--plan-sha256", default="")
    parser.add_argument("--plan-semantic-sha256", default="")
    parser.add_argument("--state-lineage-sha256", default="")
    parser.add_argument("--state-serial", type=int, default=-1)
    parser.add_argument("--approval-sha256", default="")
    parser.add_argument("--preflight-sha256", default="")
    parser.add_argument("--prepare-sha256", default="")
    args = parser.parse_args()
    try:
        if not DIGEST.fullmatch(args.authorization_sha256) or not DIGEST.fullmatch(args.operation_id):
            refuse("authorization digest or operation ID is invalid")
        if not COMMIT.fullmatch(args.commit):
            refuse("authorization commit is invalid")
        if digest(args.authorization) != args.authorization_sha256:
            refuse("authorization file digest differs")
        authorization, contract, journal = read(args.authorization), read(args.contract), read(args.journal)
        common_keys = {
            "schema_version", "phase", "status", "integrated_commit", "operation_id", "node",
            "direction", "mode", "contract_sha256", "journal_sha256", "expires_at", "raw_values_recorded",
        }
        apply_keys = {
            "journal_generation", "plan_sha256", "plan_semantic_sha256", "state_lineage_sha256",
            "state_serial", "approval_sha256", "preflight_sha256", "prepare_sha256",
            "capability_secret_sha256", "capability_hmac_sha256",
        }
        expected_keys = common_keys | (apply_keys if args.mode == "apply" else set())
        if set(authorization) != expected_keys:
            refuse("authorization schema differs")
        expected = {
            "schema_version": 1, "phase": 6,
            "status": "CONTROLLER_APPLY_AUTHORIZED" if args.mode == "apply" else "CONTROLLER_OPERATION_AUTHORIZED",
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
        expected_state = {"prepare": "PREPARED", "apply": "APPLYING", "recover": "APPLIED"}[args.mode]
        if (
            journal.get("schema_version") != 1 or journal.get("phase") != 6
            or journal.get("integrated_commit") != args.commit
            or journal.get("operation_id") != args.operation_id
            or journal.get("node") != args.node or journal.get("direction") != args.direction
            or journal.get("state") != expected_state
        ):
            refuse("operation journal is not in the exact authorized state")
        if args.mode == "apply":
            supplied_digests = (
                args.plan_sha256, args.plan_semantic_sha256, args.state_lineage_sha256,
                args.approval_sha256, args.preflight_sha256, args.prepare_sha256,
            )
            if (
                args.repository is None or args.capability_secret is None
                or any(not DIGEST.fullmatch(value) for value in supplied_digests)
                or args.journal_generation < 1 or args.state_serial < 0
            ):
                refuse("apply authorization arguments are incomplete")
            apply_expected = {
                "journal_generation": args.journal_generation,
                "plan_sha256": args.plan_sha256,
                "plan_semantic_sha256": args.plan_semantic_sha256,
                "state_lineage_sha256": args.state_lineage_sha256,
                "state_serial": args.state_serial,
                "approval_sha256": args.approval_sha256,
                "preflight_sha256": args.preflight_sha256,
                "prepare_sha256": args.prepare_sha256,
            }
            if any(authorization.get(key) != value for key, value in apply_expected.items()):
                refuse("apply authorization reviewed binding differs")
            secret = dpapi_unprotect(args.capability_secret)
            secret_digest = hashlib.sha256(secret).hexdigest()
            supplied_hmac = authorization.get("capability_hmac_sha256")
            unsigned = dict(authorization)
            unsigned.pop("capability_hmac_sha256", None)
            expected_hmac = hmac.new(
                secret, json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            if (
                authorization.get("capability_secret_sha256") != secret_digest
                or not isinstance(supplied_hmac, str) or not hmac.compare_digest(supplied_hmac, expected_hmac)
            ):
                refuse("apply capability HMAC proof differs")
            if (
                journal.get("generation") != args.journal_generation
                or journal.get("plan_sha256") != args.plan_sha256
                or journal.get("state_lineage_sha256") != args.state_lineage_sha256
                or journal.get("state_serial_before") != args.state_serial
                or journal.get("review_sha256") != args.approval_sha256
                or journal.get("prepare_sha256") != args.prepare_sha256
            ):
                refuse("APPLYING journal differs from the reviewed capability")
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=args.repository, check=False,
                capture_output=True, text=True,
            )
            dirty = subprocess.run(
                ["git", "status", "--porcelain=v2", "--untracked-files=all"], cwd=args.repository,
                check=False, capture_output=True, text=True,
            )
            if head.returncode != 0 or head.stdout.strip() != args.commit or dirty.returncode != 0 or dirty.stdout.strip():
                refuse("apply authorization requires the exact clean integrated commit")
        print('{"schema_version":1,"status":"AUTHORIZED"}')
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
