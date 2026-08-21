#!/usr/bin/env python3
"""Durable Phase 6 broker store and read-only admission boundary.

This module intentionally contains no effect adapter.  Its executable entry
point always refuses.  It only persists already-reduced journals, validates
admission artifacts, and collects fixed sanitized read-only observations.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import stat
import sys
import tempfile
from typing import Any, Callable, Iterator


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase6_transaction_broker_model", HERE / "transaction-broker-model.py")
assert SPEC and SPEC.loader
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)

DIGEST = MODEL.DIGEST
STORE_RECEIPT_KEYS = {"schema_version", "operation_id", "generation", "lease_epoch", "journal_sha256",
                      "nonce_ledger_sha256", "written_at", "raw_values_recorded"}
READ_ONLY_COMMANDS = {
    "cluster-members": ("kubectl", "get", "nodes", "-o", "json"),
    "terraform-state": ("terraform", "show", "-json"),
    "provider-inventory": ("verda", "instance", "list", "--json"),
}


class StoreRefused(ValueError):
    pass


def refuse(message: str) -> None:
    raise StoreRefused(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_text(value: dt.datetime) -> str:
    if value.tzinfo is None or value.microsecond:
        refuse("store clock must be timezone-aware exact seconds")
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_base() -> pathlib.Path:
    configured = os.environ.get("VERDA_TAKEHOME_CONFIG_DIR")
    if configured:
        return pathlib.Path(configured)
    if os.name == "nt":
        return pathlib.Path(os.environ["LOCALAPPDATA"]) / "VerdaPlatformTakehome"
    return pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(pathlib.Path.home() / ".config"))) / "verda-takehome"


def default_security_probe(path: pathlib.Path) -> dict[str, Any]:
    status = path.lstat()
    return {"reparse": stat.S_ISLNK(status.st_mode) or bool(getattr(status, "st_file_attributes", 0) & 0x400),
            "nlink": status.st_nlink, "device": status.st_dev, "identity": status.st_ino,
            "owner_only": not bool(status.st_mode & (stat.S_IRWXG | stat.S_IRWXO))}


class NamedMutex:
    """OS mutex in production; process lock fallback keeps tests deterministic."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.handle: Any = None
        self.abandoned = False

    def __enter__(self) -> "NamedMutex":
        if os.name == "nt":
            import ctypes
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.name)
            if not self.handle:
                refuse("unable to create the named broker/state mutex")
            result = ctypes.windll.kernel32.WaitForSingleObject(self.handle, 0)
            if result == 0x80:
                self.abandoned = True
            elif result == 0x102:
                ctypes.windll.kernel32.CloseHandle(self.handle); self.handle = None
                refuse("another writer holds the named broker/state mutex")
            elif result != 0:
                ctypes.windll.kernel32.CloseHandle(self.handle); self.handle = None
                refuse("named broker/state mutex wait failed")
        else:
            import fcntl
            lock_path = pathlib.Path(tempfile.gettempdir()) / f"verda-{digest_bytes(self.name.encode())}.lock"
            self.handle = open(lock_path, "a+b")
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                self.handle.close(); self.handle = None
                refuse("another writer holds the named broker/state mutex")
        return self

    def __exit__(self, *_: Any) -> None:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)
        elif self.handle:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


class DurableBrokerStore:
    def __init__(self, *, operation_id: str, base: pathlib.Path | None = None,
                 clock: Callable[[], dt.datetime], security_probe: Callable[[pathlib.Path], dict[str, Any]] = default_security_probe,
                 verifier: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 state_path: pathlib.Path | None = None,
                 crash_hook: Callable[[str], None] = lambda _stage: None) -> None:
        if not DIGEST.fullmatch(operation_id):
            refuse("store operation identity differs")
        canonical_base = (base or default_base())
        if not canonical_base.is_absolute():
            refuse("Phase 2 Base must be absolute")
        self.base = canonical_base
        self.root = canonical_base / "phase6-resize-control"
        self.operation_id = operation_id
        self.envelope_path = self.root / f"broker-{operation_id}.envelope-v2.json"
        self.temp_path = self.root / f"broker-{operation_id}.envelope-v2.tmp"
        self.clock, self.security_probe, self.verifier, self.crash_hook = clock, security_probe, verifier, crash_hook
        self.operation_mutex = f"Local\\VerdaPhase6Broker-{operation_id}"
        canonical_state = str((state_path or (canonical_base / "terraform.tfstate")).resolve(strict=False)).lower()
        self.state_mutex = f"Local\\VerdaPhase2State-{digest_bytes(canonical_state.encode('utf-8'))}"

    def _secure(self, path: pathlib.Path, *, regular: bool = False) -> dict[str, Any]:
        absolute = path.absolute()
        if absolute != path:
            refuse("broker path is not absolute canonical input")
        cursor = absolute
        while cursor != cursor.parent:
            if cursor.exists():
                facts = self.security_probe(cursor)
                if facts.get("reparse"):
                    refuse("broker path traverses a symlink/junction/reparse point")
                if not facts.get("owner_only", False):
                    refuse("broker path ACL is not owner-only")
                if regular and cursor == absolute and facts.get("nlink") != 1:
                    refuse("broker protected file has aliases/hardlinks")
            cursor = cursor.parent
        return self.security_probe(absolute) if absolute.exists() else {}

    def initialize(self) -> None:
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        self._secure(self.base)
        self._secure(self.root)
        if self.root.resolve(strict=True) != (self.base.resolve(strict=True) / "phase6-resize-control"):
            refuse("control root is not canonical Base\\phase6-resize-control")

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        with NamedMutex(self.operation_mutex), NamedMutex(self.state_mutex):
            yield

    def _read_json(self, path: pathlib.Path) -> dict[str, Any]:
        before = self._secure(path, regular=True)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            refuse(f"durable store contains torn/invalid {path.name}: {type(error).__name__}")
        if not isinstance(value, dict):
            refuse("durable store JSON is not an object")
        after = self._secure(path, regular=True)
        if (before.get("device"), before.get("identity")) != (after.get("device"), after.get("identity")):
            refuse("protected file identity changed while reading")
        return value

    def load(self) -> dict[str, Any]:
        self.initialize()
        self._recover()
        envelope = self._read_json(self.envelope_path)
        if set(envelope) != {"schema_version", "operation_id", "journal", "nonces"} \
                or envelope["schema_version"] != 2 or envelope["operation_id"] != self.operation_id:
            refuse("durable broker envelope differs")
        journal = envelope["journal"]
        MODEL.validate_journal(journal)
        if journal["operation_id"] != self.operation_id:
            refuse("stored journal operation differs")
        expected_nonces = [entry["cas_nonce"] for entry in journal["history"]]
        if envelope["nonces"] != expected_nonces or len(expected_nonces) != len(set(expected_nonces)):
            refuse("envelope nonce ledger does not exactly replay journal history")
        return journal

    def _recover(self) -> None:
        if not self.temp_path.exists():
            return
        staged = self._read_json(self.temp_path)
        if self.envelope_path.exists():
            current = self._read_json(self.envelope_path)
            chosen = current if current.get("journal", {}).get("generation", -1) >= staged.get("journal", {}).get("generation", -1) else staged
        else:
            chosen = staged
        if set(chosen) != {"schema_version", "operation_id", "journal", "nonces"}:
            refuse("torn envelope staging manifest differs")
        MODEL.validate_journal(chosen["journal"])
        os.replace(self.temp_path, self.envelope_path) if chosen is staged else self.temp_path.unlink()

    def _atomic(self, path: pathlib.Path, value: dict[str, Any], temp: pathlib.Path) -> None:
        raw = canonical_bytes(value) + b"\n"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.crash_hook("after_temp_fsync")
        os.replace(temp, path)
        self.crash_hook("after_replace")
        if os.name != "nt":
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        self.crash_hook("after_directory_fsync")

    def cas(self, journal: dict[str, Any], *, expected_generation: int, expected_lease_epoch: int,
            expected_cas_nonce: str | None, expected_head_sha256: str | None) -> dict[str, Any]:
        MODEL.validate_journal(journal)
        if journal["operation_id"] != self.operation_id:
            refuse("CAS operation differs")
        with self.locked():
            self.initialize()
            current = self.load() if self.envelope_path.exists() or self.temp_path.exists() else None
            if current is not None and (current["generation"] != expected_generation
                                        or current["lease_epoch"] != expected_lease_epoch):
                refuse("CAS generation/lease epoch is stale")
            if current is None and (expected_generation != 0 or expected_lease_epoch != 0):
                refuse("initial CAS expectation differs")
            if current is None:
                if expected_cas_nonce is not None or expected_head_sha256 is not None \
                        or journal["generation"] != 1 or journal["lease_epoch"] < 1 \
                        or len(journal["history"]) != 1 or journal["history"][0]["event"] != "START_SPEC":
                    refuse("initial CAS is not exact START_SPEC genesis")
            else:
                head = current["history"][-1]
                if expected_cas_nonce != current["cas_nonce"] or expected_head_sha256 != head["entry_sha256"]:
                    refuse("CAS current nonce/head hash differs")
                if canonical_bytes(journal["history"][:-1]) != canonical_bytes(current["history"]):
                    refuse("CAS candidate forks or rewrites stored history")
            if current is not None and journal["generation"] != current["generation"] + 1:
                refuse("CAS journal did not advance exactly one generation")
            nonces = [entry["cas_nonce"] for entry in journal["history"]]
            if len(nonces) != len(set(nonces)):
                refuse("CAS nonce replayed in candidate history")
            envelope = {"schema_version": 2, "operation_id": self.operation_id,
                        "journal": journal, "nonces": nonces}
            self._atomic(self.envelope_path, envelope, self.temp_path)
            now = utc_text(self.clock())
            return {"schema_version": 1, "operation_id": self.operation_id,
                    "generation": journal["generation"], "lease_epoch": journal["lease_epoch"],
                    "journal_sha256": digest_bytes(canonical_bytes(journal)),
                    "nonce_ledger_sha256": digest_bytes(canonical_bytes(nonces)), "written_at": now,
                    "raw_values_recorded": False}

    def adopt_read_only(self, *, policy: dict[str, Any], lease: Any, boundary: dict[str, Any],
                        nonce_source: Callable[[], str]) -> dict[str, Any]:
        """Reacquire and persist only the model's read-only crash-adoption event."""
        with self.locked():
            current = self.load()
            adopted = MODEL.adopt_spec_journal(policy=policy, journal=current, lease=lease,
                                               expected_generation=current["generation"],
                                               expected_nonce=current["cas_nonce"], boundary=boundary,
                                               now=self.clock(), nonce_source=nonce_source)
        # CAS obtains fresh mutexes and rechecks generation/epoch; no effect can
        # occur between adoption calculation and its durable comparison.
        self.cas(adopted, expected_generation=current["generation"],
                 expected_lease_epoch=current["lease_epoch"], expected_cas_nonce=current["cas_nonce"],
                 expected_head_sha256=current["history"][-1]["entry_sha256"])
        return adopted

    def verify_admission(self, *, authorization: dict[str, Any], artifacts: dict[str, pathlib.Path]) -> dict[str, Any]:
        required = {"broker", "policy", "rollback_policy", "contract", "tool_lock", "review",
                    "plan", "state", "pre_backup", "post_backup"}
        expected_hashes = authorization.get("artifact_hashes")
        if (set(artifacts) != required or not isinstance(expected_hashes, dict)
                or set(expected_hashes) != required or self.verifier is None
                or authorization.get("operation_id") != self.operation_id):
            refuse("admission artifact/hash/verifier boundary differs")
        receipt = self.verifier(authorization)
        if (not isinstance(receipt, dict) or receipt.get("requires_reverification_before_use") is not True
                or receipt.get("operation_id") != self.operation_id
                or receipt.get("artifact_hashes") != expected_hashes):
            refuse("direct synchronous authorization verifier refused or projected different hashes")
        measured: dict[str, str] = {}
        for name in sorted(required):
            path = artifacts[name]
            before = self._secure(path, regular=True)
            measured[name] = digest_bytes(path.read_bytes())
            after = self._secure(path, regular=True)
            if (before.get("device"), before.get("identity")) != (after.get("device"), after.get("identity")):
                refuse(f"admission {name} identity changed during hash")
            if measured[name] != expected_hashes[name]:
                refuse(f"admission {name} hash differs")
        return {"operation_id": self.operation_id, "measured_hashes": measured,
                "verifier_receipt_sha256": digest_bytes(canonical_bytes(receipt)),
                "observed_at": utc_text(self.clock()), "raw_values_recorded": False}


class ReadOnlyAdmissionAdapter:
    def __init__(self, runner: Callable[[tuple[str, ...]], tuple[int, str, str]], clock: Callable[[], dt.datetime]) -> None:
        self.runner, self.clock = runner, clock

    def collect(self, kind: str) -> dict[str, Any]:
        if kind not in READ_ONLY_COMMANDS:
            refuse("read-only adapter command is not fixed/allowed")
        command = READ_ONLY_COMMANDS[kind]
        started = self.clock()
        code, stdout, stderr = self.runner(command)
        ended = self.clock()
        if code != 0 or stderr.strip():
            refuse("read-only adapter failed or emitted stderr")
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            refuse("read-only adapter output is not JSON")
        duration = (ended - started).total_seconds()
        if duration < 0 or duration > 10:
            refuse("read-only adapter receipt is slow/stale")
        if not isinstance(parsed, dict):
            refuse("read-only adapter aggregate source is not an object")
        if kind == "cluster-members":
            items = parsed.get("items")
            if not isinstance(items, list): refuse("cluster member aggregate schema differs")
            aggregate = {"member_count": len(items),
                         "ready_count": sum(1 for item in items if isinstance(item, dict)
                                            and item.get("ready") is True)}
        elif kind == "provider-inventory":
            items = parsed.get("instances")
            if not isinstance(items, list): refuse("provider inventory aggregate schema differs")
            aggregate = {"instance_count": len(items)}
        else:
            values = parsed.get("values")
            if not isinstance(values, dict): refuse("Terraform state aggregate schema differs")
            resources = values.get("root_module", {}).get("resources", [])
            if not isinstance(resources, list): refuse("Terraform resource aggregate schema differs")
            aggregate = {"resource_count": len(resources)}
        sanitized = {"kind": kind, "command_sha256": digest_bytes(canonical_bytes(command)),
                     "started_at": utc_text(started), "ended_at": utc_text(ended),
                     "duration_ms": int(duration * 1000), "freshness_seconds": 10,
                     "aggregate": aggregate, "raw_values_recorded": False}
        return sanitized


def main() -> int:
    print("REFUSED: durable Phase 6 broker store has no effect adapter or execution route", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
