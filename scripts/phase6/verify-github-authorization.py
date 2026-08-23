#!/usr/bin/env python3
"""Read-only verifier for one dormant Phase 6 TRANSACTION authorization.

The receipt is deliberately non-capable: a future broker must invoke this verifier
again synchronously while holding its operation lease.  No mutation route consumes
the receipt shipped by this repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Protocol


REPOSITORY = "kaycee1771/verda-platform-takehome"
ORIGIN = "https://github.com/kaycee1771/verda-platform-takehome.git"
MAIN_REF = "refs/heads/main"
WORKFLOW_ID = 335664221
WORKFLOW_PATH = ".github/workflows/validate.yml"
WORKFLOW_CONTEXT = "Credential-free quality gates"
WORKFLOW_APP_ID = 15368
TRUSTED_MERGER = "kaycee1771"
WEB_FLOW_FINGERPRINT = "968479A1AFF927E37D1A566BB5690EEEBB952194"
WEB_FLOW_KEY_ID = "B5690EEEBB952194"
WEB_FLOW_PUBLIC_KEY_DIGEST = "40ce89d21fb075092d256f9fbf62a1c19299d3282cb913d3e61d08235d0c491a"
WINDOWS_GIT_SHA256 = "c954fcc8e65a38450895ca65d308ecaee63f044d16494b5385faa5e036a3facb"
WINDOWS_GIT_VERSION = "git version 2.50.1.windows.1"
WINDOWS_GPG_SHA256 = "22356f7af9f43c98339a51cee22ab9930688b699f71c5f964b0b07dfa0bc0d73"
WINDOWS_GPG_VERSION_PREFIX = "gpg (GnuPG) 2.4.7"
APPROVED_EXPIRY = "2026-08-27T21:00:00Z"
APPROVED_COST = "70.46"
MINIMUM_RECOVERY_MARGIN_SECONDS = 86400
MAXIMUM_TRANSACTION_SECONDS = 14400
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")

AUTHORIZATION_KEYS = {
    "schema_version", "phase", "status", "authorization_mode", "repository", "workflow_id",
    "pr_number", "source_parent_commit", "source_tree_oid", "source_tree_manifest_sha256",
    "operation_id", "operation_nonce", "node", "direction", "plan_sha256",
    "plan_semantic_sha256", "state_lineage_sha256", "state_serial", "contract_sha256",
    "tool_lock_sha256", "broker_sha256", "transaction_policy_sha256", "rollback_policy_sha256",
    "journal_sha256", "journal_generation", "journal_state",
    "user_approval_sha256", "security_review_sha256", "reliability_review_sha256",
    "security_approved", "reliability_approved", "preflight_sha256", "cost_sha256",
    "capacity_sha256", "collector_sha256", "etcd_backup_sha256", "data_backup_sha256",
    "provider_facts_sha256", "approved_resource_expiry_utc", "approved_cost_ceiling_usd",
    "issued_at", "start_by", "complete_by", "minimum_recovery_margin_seconds",
    "raw_values_recorded",
}
DIGEST_KEYS = {
    "source_tree_manifest_sha256", "operation_id", "operation_nonce", "plan_sha256",
    "plan_semantic_sha256", "state_lineage_sha256", "contract_sha256", "tool_lock_sha256",
    "broker_sha256", "transaction_policy_sha256", "rollback_policy_sha256",
    "journal_sha256",
    "user_approval_sha256", "security_review_sha256", "reliability_review_sha256",
    "preflight_sha256", "cost_sha256", "capacity_sha256", "collector_sha256",
    "etcd_backup_sha256", "data_backup_sha256", "provider_facts_sha256",
}
MINIMAL_ENV_KEYS = {
    "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "LANG", "LC_ALL",
}


class AuthorizationRefused(ValueError):
    pass


def refuse(message: str) -> None:
    raise AuthorizationRefused(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        refuse(f"attested tool is unreadable: {type(error).__name__}")
    return digest.hexdigest()


def parse_object_bytes(payload: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                refuse(f"{label} contains a duplicate JSON field")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: refuse(f"{label} contains a non-finite JSON number"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        refuse(f"{label} is unreadable: {type(error).__name__}")
    if not isinstance(value, dict):
        refuse(f"{label} is not one JSON object")
    return value


def read_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        return parse_object_bytes(path.read_bytes(), label)
    except OSError as error:
        refuse(f"{label} is unreadable: {type(error).__name__}")


def parse_timestamp(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        refuse(f"{label} is not an exact UTC timestamp")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        refuse(f"{label} is invalid")


def utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        refuse("verification clock is not UTC-aware")
    return value.astimezone(dt.timezone.utc)


class RepositoryView(Protocol):
    root: pathlib.Path
    def origin(self) -> str: ...
    def clean(self) -> bool: ...
    def head(self) -> str: ...
    def parents(self, commit: str) -> list[str]: ...
    def first_parent_commits(self, commit: str) -> list[str]: ...
    def changed_entries(self, parent: str, commit: str) -> list[tuple[str, str]]: ...
    def path_exists(self, commit: str, path: str) -> bool: ...
    def tree_oid(self, commit: str) -> str: ...
    def tree_manifest_sha256(self, commit: str) -> str: ...
    def tracked_blob(self, commit: str, path: str) -> bytes: ...
    def tracked_paths(self, commit: str, prefix: str) -> list[str]: ...
    def commit_metadata(self, commit: str) -> tuple[str, str, str]: ...
    def signature_fingerprint(self, commit: str) -> str: ...


class GitRepository:
    """Canonical local Git view with attested, absolute executables and no caller Git config."""

    def __init__(self, root: pathlib.Path) -> None:
        expected = pathlib.Path(__file__).resolve().parents[2]
        supplied = pathlib.Path(os.path.abspath(root))
        resolved = root.resolve(strict=True)
        if root.is_symlink() or os.path.normcase(str(supplied)) != os.path.normcase(str(resolved)) or resolved != expected:
            refuse("repository root is not the verifier's exact canonical checkout")
        if os.name != "nt":
            refuse("production authorization verification requires the protected Windows host")
        self.root = resolved
        self.git = self._attest_git()
        self.gpg = self._attest_gpg()

    @staticmethod
    def _resolve_exact() -> pathlib.Path:
        candidate = pathlib.Path(r"C:\Program Files\Git\cmd\git.exe")
        if not candidate.is_file():
            refuse("attested tool is unavailable")
        path = candidate
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_file() or not resolved.is_absolute():
            refuse("attested tool path differs")
        return resolved

    @staticmethod
    def _minimal_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        source = {key.upper(): (key, value) for key, value in os.environ.items()}
        environment = {source[key][0]: source[key][1] for key in MINIMAL_ENV_KEYS if key in source}
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
        })
        if extra:
            environment.update(extra)
        return environment

    def _attest_git(self) -> pathlib.Path:
        path = self._resolve_exact()
        if sha256_file(path) != WINDOWS_GIT_SHA256:
            refuse("Git executable digest differs from the reviewed tool lock")
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True, check=False,
                                env=self._minimal_environment())
        if result.returncode != 0 or result.stdout.strip() != WINDOWS_GIT_VERSION:
            refuse("Git executable version differs from the reviewed tool lock")
        return path

    def _attest_gpg(self) -> pathlib.Path:
        candidate = self.git.parents[1] / "usr" / "bin" / "gpg.exe"
        if not candidate.is_file():
            refuse("bundled OpenPGP verifier is unavailable")
        path = candidate.resolve(strict=True)
        if sha256_file(path) != WINDOWS_GPG_SHA256:
            refuse("OpenPGP executable digest differs from the reviewed tool lock")
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True, check=False,
                                env=self._minimal_environment())
        if result.returncode != 0 or not result.stdout.startswith(WINDOWS_GPG_VERSION_PREFIX):
            refuse("OpenPGP executable version differs from the reviewed tool lock")
        return path

    def _base(self) -> list[str]:
        return [str(self.git), "--no-replace-objects", "-c", f"safe.directory={self.root.as_posix()}",
                "-c", "core.fsmonitor=false"]

    def _run(self, arguments: list[str], *, text: bool = True,
             env: dict[str, str] | None = None, allow_failure: bool = False) -> Any:
        result = subprocess.run(self._base() + arguments, cwd=self.root, capture_output=True, text=text,
                                check=False, env=self._minimal_environment(env))
        if result.returncode != 0 and not allow_failure:
            refuse("canonical Git repository verification failed")
        return result if allow_failure else result.stdout

    def origin(self) -> str:
        return self._run(["remote", "get-url", "origin"]).strip()

    def clean(self) -> bool:
        return not self._run(["status", "--porcelain=v2", "--untracked-files=all"]).strip()

    def head(self) -> str:
        return self._run(["rev-parse", "HEAD"]).strip()

    def parents(self, commit: str) -> list[str]:
        return self._run(["rev-list", "--parents", "-n", "1", commit]).strip().split()[1:]

    def first_parent_commits(self, commit: str) -> list[str]:
        values = self._run(["rev-list", "--first-parent", "--max-count=10001", commit]).strip().splitlines()
        if not values or len(values) > 10000 or any(not COMMIT.fullmatch(value) for value in values):
            refuse("canonical first-parent authorization history is absent or exceeds its bound")
        return values

    def changed_entries(self, parent: str, commit: str) -> list[tuple[str, str]]:
        raw = self._run(["diff-tree", "--no-commit-id", "--name-status", "--no-renames", "-r", "-z", parent, commit], text=False)
        parts = [part.decode("utf-8") for part in raw.split(b"\0") if part]
        if len(parts) % 2:
            refuse("authorization commit diff differs")
        return list(zip(parts[0::2], parts[1::2]))

    def path_exists(self, commit: str, path: str) -> bool:
        result = self._run(["cat-file", "-e", f"{commit}:{path}"], allow_failure=True)
        return result.returncode == 0

    def tree_oid(self, commit: str) -> str:
        return self._run(["rev-parse", f"{commit}^{{tree}}"]).strip()

    def tree_manifest_sha256(self, commit: str) -> str:
        return hashlib.sha256(self._run(["ls-tree", "-r", "-z", "--full-tree", commit], text=False)).hexdigest()

    @staticmethod
    def _safe_path(path: str) -> None:
        if path.startswith("/") or ".." in pathlib.PurePosixPath(path).parts or "\\" in path:
            refuse("tracked authorization path is invalid")

    def tracked_blob(self, commit: str, path: str) -> bytes:
        self._safe_path(path)
        return self._run(["show", f"{commit}:{path}"], text=False)

    def tracked_paths(self, commit: str, prefix: str) -> list[str]:
        self._safe_path(prefix)
        raw = self._run(["ls-tree", "-r", "--name-only", "-z", commit, "--", prefix], text=False)
        return [part.decode("utf-8") for part in raw.split(b"\0") if part]

    def commit_metadata(self, commit: str) -> tuple[str, str, str]:
        raw = self._run(["show", "-s", "--format=%cn%x00%ce%x00%s", commit], text=False)
        parts = raw.rstrip(b"\n").split(b"\0")
        if len(parts) != 3:
            refuse("authorization commit metadata differs")
        return tuple(part.decode("utf-8") for part in parts)  # type: ignore[return-value]

    def signature_fingerprint(self, commit: str) -> str:
        directory = self.root / "config" / "phase6-authorizations"
        key = directory / "github-web-flow.gpg.asc"
        provenance = read_object(directory / "github-web-flow-key.provenance.json", "web-flow key provenance")
        if key.is_symlink() or not key.is_file() or sha256_file(key) != WEB_FLOW_PUBLIC_KEY_DIGEST:
            refuse("vendored web-flow key digest differs")
        if provenance != {
            "schema_version": 1, "source": "https://api.github.com/users/web-flow/gpg_keys",
            "raw_endpoint": "https://github.com/web-flow.gpg", "api_record_id": 3040729,
            "retrieval_date_utc": "2026-08-21", "armored_sha256": WEB_FLOW_PUBLIC_KEY_DIGEST,
            "accepted_primary_fingerprint": WEB_FLOW_FINGERPRINT, "accepted_key_id": WEB_FLOW_KEY_ID,
            "accepted_uid": "GitHub <noreply@github.com>", "raw_values_recorded": False,
        }:
            refuse("vendored web-flow key provenance differs")
        with tempfile.TemporaryDirectory(prefix="phase6-web-flow-") as home:
            environment = self._minimal_environment({"GNUPGHOME": home})
            imported = subprocess.run([str(self.gpg), "--batch", "--import", str(key)], check=False,
                                      capture_output=True, env=environment)
            fingerprints = subprocess.run([str(self.gpg), "--batch", "--with-colons", "--fingerprint"],
                                          check=False, capture_output=True, text=True, env=environment)
            if (imported.returncode not in {0, 2} or fingerprints.returncode != 0 or
                    f"fpr:::::::::{WEB_FLOW_FINGERPRINT}:" not in fingerprints.stdout):
                refuse("vendored web-flow key fingerprint differs")
            result = subprocess.run(self._base() + ["-c", f"gpg.program={self.gpg.as_posix()}",
                                    "verify-commit", "--raw", commit], cwd=self.root, check=False,
                                    capture_output=True, text=True, env=environment)
            match = re.search(r"\[GNUPG:\] VALIDSIG ([0-9A-F]{40}) ", result.stderr + result.stdout)
            if result.returncode != 0 or match is None:
                refuse("authorization commit lacks a valid pinned web-flow signature")
            return match.group(1)


class GitHubView(Protocol):
    def main_head(self) -> str: ...
    def commit_tree(self, commit: str) -> str: ...
    def pull_request(self, number: int) -> dict[str, Any]: ...
    def workflow_runs(self, head_sha: str) -> list[dict[str, Any]]: ...
    def branch_protection(self) -> dict[str, Any]: ...
    def repository_settings(self) -> dict[str, Any]: ...
    def required_signatures_enabled(self) -> bool: ...


class GitHubAPI:
    """Fixed-origin, read-only GitHub metadata client. No caller URLs or tokens are accepted."""

    def _get(self, path: str, query: dict[str, str] | None = None, *,
             allow_not_found: bool = False) -> dict[str, Any] | None:
        if (path and not re.fullmatch(r"[A-Za-z0-9_./-]+", path)) or path.startswith("/") or ".." in path:
            refuse("GitHub metadata path differs")
        url = f"https://api.github.com/repos/{REPOSITORY}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "verda-phase6-transaction-auth-v1",
        })
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPSHandler(context=ssl.create_default_context()))
            with opener.open(request, timeout=20) as response:
                payload = response.read(8 * 1024 * 1024 + 1)
                if len(payload) > 8 * 1024 * 1024:
                    refuse("canonical GitHub metadata response is oversized")
                value = parse_object_bytes(payload, "canonical GitHub metadata response")
        except urllib.error.HTTPError as error:
            if allow_not_found and error.code == 404:
                return None
            refuse("canonical GitHub metadata verification failed")
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            refuse("canonical GitHub metadata verification failed")
        if not isinstance(value, dict):
            refuse("canonical GitHub metadata response differs")
        return value

    def main_head(self) -> str:
        value = self._get("git/ref/heads/main")
        target = value.get("object")
        if (value.get("ref") != MAIN_REF or not isinstance(target, dict) or target.get("type") != "commit"
                or not isinstance(target.get("sha"), str) or not COMMIT.fullmatch(target["sha"])):
            refuse("canonical GitHub main reference differs")
        return target["sha"]

    def commit_tree(self, commit: str) -> str:
        if not COMMIT.fullmatch(commit):
            refuse("canonical GitHub commit identity differs")
        tree = self._get(f"git/commits/{commit}").get("tree")
        if not isinstance(tree, dict) or not isinstance(tree.get("sha"), str) or not COMMIT.fullmatch(tree["sha"]):
            refuse("canonical GitHub commit tree differs")
        return tree["sha"]

    def pull_request(self, number: int) -> dict[str, Any]:
        return self._get(f"pulls/{number}")

    def branch_protection(self) -> dict[str, Any]:
        return self._get("branches/main/protection")

    def repository_settings(self) -> dict[str, Any]:
        value = self._get("")
        assert isinstance(value, dict)
        return value

    def required_signatures_enabled(self) -> bool:
        value = self._get("branches/main/protection/required_signatures", allow_not_found=True)
        if value is None:
            # GitHub's fixed endpoint returns 404 when signatures are disabled.  The
            # enclosing check already proved this public branch's protection readable.
            return False
        if set(value) - {"url", "enabled"} or type(value.get("enabled")) is not bool:
            refuse("protected main signature-policy response differs")
        return value["enabled"]

    def workflow_runs(self, head_sha: str) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        reported_total: int | None = None
        for page in range(1, 11):
            value = self._get(f"actions/workflows/{WORKFLOW_ID}/runs", {
                "event": "pull_request", "head_sha": head_sha, "per_page": "100", "page": str(page),
            })
            total = value.get("total_count")
            page_runs = value.get("workflow_runs")
            if type(total) is not int or total < 0 or not isinstance(page_runs, list) or not all(
                    isinstance(run, dict) for run in page_runs):
                refuse("canonical GitHub workflow response differs")
            if reported_total is None:
                reported_total = total
            elif total != reported_total:
                refuse("canonical GitHub workflow pagination changed during verification")
            runs.extend(page_runs)
            if len(page_runs) < 100:
                break
        else:
            refuse("canonical GitHub workflow response is truncated")
        if reported_total is None or len(runs) != reported_total:
            refuse("canonical GitHub workflow response is truncated")
        identifiers: set[int] = set()
        for run in runs:
            identifier = run.get("id")
            if type(identifier) is not int or identifier < 1 or identifier in identifiers:
                refuse("canonical GitHub workflow run identities differ or repeat")
            identifiers.add(identifier)
        return runs


def _empty(value: object) -> bool:
    return value in (None, False) or value == [] or value == {}


def _empty_actor_allowance(value: object) -> bool:
    if _empty(value):
        return True
    return (isinstance(value, dict) and set(value) <= {"users", "teams", "apps"}
            and all(value.get(key, []) == [] for key in ("users", "teams", "apps")))


def verify_governance(github: GitHubView) -> None:
    protection = github.branch_protection()
    checks = protection.get("required_status_checks")
    admins = protection.get("enforce_admins")
    reviews = protection.get("required_pull_request_reviews")
    if not isinstance(checks, dict) or checks.get("strict") is not True:
        refuse("protected main strict status policy differs")
    contexts = checks.get("contexts")
    required = checks.get("checks")
    if contexts != [WORKFLOW_CONTEXT] or required != [{"context": WORKFLOW_CONTEXT, "app_id": WORKFLOW_APP_ID}]:
        refuse("protected main app-bound status policy differs")
    if not isinstance(admins, dict) or admins.get("enabled") is not True:
        refuse("protected main does not enforce policy for administrators")
    if not isinstance(reviews, dict) or reviews.get("required_approving_review_count") != 0:
        refuse("protected main pull-request policy differs")
    if not _empty_actor_allowance(reviews.get("bypass_pull_request_allowances")):
        refuse("protected main pull-request bypass differs")
    for key, label, expected in (
        ("allow_force_pushes", "force-push", False), ("allow_deletions", "deletion", False),
        ("required_linear_history", "linear-history", True),
    ):
        setting = protection.get(key)
        if not isinstance(setting, dict) or setting.get("enabled") is not expected:
            refuse(f"protected main {label} policy differs")
    if not _empty(protection.get("restrictions")):
        refuse("protected main actor restrictions differ")
    if github.required_signatures_enabled() is not False:
        refuse("protected main signature-policy residual differs")
    repository = github.repository_settings()
    if (repository.get("full_name") != REPOSITORY or repository.get("default_branch") != "main"
            or repository.get("allow_squash_merge") is not True
            or repository.get("allow_merge_commit") is not False
            or repository.get("allow_rebase_merge") is not False):
        refuse("canonical repository squash-only policy differs")


def validate_binding(binding: dict[str, Any], operation_id: str) -> None:
    if set(binding) != AUTHORIZATION_KEYS:
        refuse("local reviewed transaction binding schema differs")
    fixed = {
        "schema_version": 1, "phase": 6, "status": "GITHUB_PROTECTED_MAIN_AUTHORIZED",
        "authorization_mode": "TRANSACTION", "repository": REPOSITORY, "workflow_id": WORKFLOW_ID,
        "operation_id": operation_id, "security_approved": True, "reliability_approved": True,
        "journal_state": "AUTHORIZED",
        "approved_resource_expiry_utc": APPROVED_EXPIRY, "approved_cost_ceiling_usd": APPROVED_COST,
        "raw_values_recorded": False,
    }
    if any(binding.get(key) != value for key, value in fixed.items()):
        refuse("reviewed transaction identity or approval differs")
    if not DIGEST.fullmatch(operation_id) or binding.get("node") not in {"01", "02", "03"} or binding.get("direction") not in {"resize", "rollback"}:
        refuse("reviewed transaction target differs")
    if any(not isinstance(binding.get(key), str) or not DIGEST.fullmatch(binding[key]) for key in DIGEST_KEYS):
        refuse("reviewed transaction digest differs")
    for key in ("source_parent_commit", "source_tree_oid"):
        if not isinstance(binding.get(key), str) or not COMMIT.fullmatch(binding[key]):
            refuse("reviewed source commit/tree differs")
    if type(binding.get("pr_number")) is not int or binding["pr_number"] < 1:
        refuse("reviewed PR identity differs")
    if type(binding.get("state_serial")) is not int or binding["state_serial"] < 0:
        refuse("reviewed state serial differs")
    if type(binding.get("journal_generation")) is not int or binding["journal_generation"] < 1:
        refuse("reviewed journal generation differs")
    if binding.get("minimum_recovery_margin_seconds") != MINIMUM_RECOVERY_MARGIN_SECONDS:
        refuse("reviewed recovery margin differs")
    approvals = [binding[key] for key in ("user_approval_sha256", "security_review_sha256", "reliability_review_sha256")]
    if len(set(approvals)) != 3 or binding["operation_nonce"] in approvals:
        refuse("user and independent review evidence is not distinct")
    if binding["operation_nonce"] in {binding[key] for key in DIGEST_KEYS - {"operation_nonce"}}:
        refuse("operation nonce is not independent from reviewed evidence")


def authorization_path_operation(path: str) -> str | None:
    match = re.fullmatch(r"config/phase6-authorizations/([0-9a-f]{64})-transaction\.json", path)
    return None if match is None else match.group(1)


def scan_authorization_history(repository: RepositoryView, head: str) -> list[dict[str, Any]]:
    """Scan immutable first-parent history and enforce an append-only authorization ledger."""
    commits = repository.first_parent_commits(head)
    candidates: list[dict[str, Any]] = []
    operations: set[str] = set()
    nonces: set[str] = set()
    for commit in reversed(commits):
        parents = repository.parents(commit)
        if not parents:
            continue
        if len(parents) != 1:
            refuse("transaction authorization is not an exact one-parent squash commit")
        parent = parents[0]
        entries = repository.changed_entries(parent, commit)
        candidate_entries = [(status, path) for status, path in entries
                             if authorization_path_operation(path) is not None]
        if not candidate_entries:
            continue
        if len(candidate_entries) != 1 or entries != candidate_entries or candidate_entries[0][0] != "A":
            refuse("transaction authorization history modified, deleted, renamed, or mixed a prior artifact")
        _, path = candidate_entries[0]
        operation_id = authorization_path_operation(path)
        assert operation_id is not None
        if repository.path_exists(parent, path):
            refuse("transaction authorization addition was already present in its parent")
        payload = repository.tracked_blob(commit, path)
        artifact = parse_object_bytes(payload, "immutable transaction authorization history")
        validate_binding(artifact, operation_id)
        if artifact["source_parent_commit"] != parent or repository.tree_oid(parent) != artifact["source_tree_oid"]:
            refuse("historical transaction authorization source parent/tree differs")
        if repository.tree_manifest_sha256(parent) != artifact["source_tree_manifest_sha256"]:
            refuse("historical transaction authorization source manifest differs")
        nonce = artifact["operation_nonce"]
        if operation_id in operations or nonce in nonces:
            refuse("operation identity or nonce was reused in immutable authorization history")
        operations.add(operation_id)
        nonces.add(nonce)
        candidates.append({"commit": commit, "parent": parent, "path": path,
                           "artifact": artifact, "payload": payload})
    tracked = {path for path in repository.tracked_paths(head, "config/phase6-authorizations")
               if authorization_path_operation(path) is not None}
    discovered = {candidate["path"] for candidate in candidates}
    if tracked != discovered:
        refuse("current authorization tree differs from immutable append-only history")
    return candidates


def authorization_times(artifact: dict[str, Any], *, now: dt.datetime | None = None) -> tuple[dt.datetime, ...]:
    issued = parse_timestamp(artifact.get("issued_at"), "authorization issued_at")
    start_by = parse_timestamp(artifact.get("start_by"), "authorization start_by")
    complete_by = parse_timestamp(artifact.get("complete_by"), "authorization complete_by")
    expiry = parse_timestamp(artifact.get("approved_resource_expiry_utc"), "approved resource expiry")
    margin = artifact.get("minimum_recovery_margin_seconds")
    if (margin != MINIMUM_RECOVERY_MARGIN_SECONDS or not issued < start_by < complete_by
            or start_by > issued + dt.timedelta(hours=1)
            or complete_by > start_by + dt.timedelta(seconds=MAXIMUM_TRANSACTION_SECONDS)
            or not complete_by + dt.timedelta(seconds=margin) < expiry):
        refuse("authorization start/completion/recovery-expiry boundary differs")
    if now is not None:
        current = utc(now)
        if issued > current + dt.timedelta(seconds=30) or not current < start_by < complete_by < expiry:
            refuse("authorization is future-dated or its transaction start window has closed")
    return issued, start_by, complete_by, expiry


def select_workflow(github: GitHubView, head_sha: str, pr_number: int) -> tuple[int, int, int]:
    exact = github.workflow_runs(head_sha)
    if not exact:
        refuse("exact hosted validation workflow did not run on the PR head")
    statuses = {"queued", "in_progress", "completed", "requested", "waiting", "pending"}
    conclusions = {"action_required", "cancelled", "failure", "neutral", "skipped", "stale",
                   "startup_failure", "success", "timed_out"}
    for run in exact:
        pulls = run.get("pull_requests")
        if (run.get("workflow_id") != WORKFLOW_ID or run.get("head_sha") != head_sha
                or run.get("event") != "pull_request" or run.get("path") != WORKFLOW_PATH
                or not isinstance(run.get("head_repository"), dict)
                or run["head_repository"].get("full_name") != REPOSITORY
                or not isinstance(pulls, list) or not pulls
                or not all(isinstance(item, dict) and type(item.get("number")) is int for item in pulls)
                or not any(item["number"] == pr_number for item in pulls)
                or any(type(run.get(key)) is not int or run[key] < 1
                       for key in ("run_number", "run_attempt", "id"))
                or run.get("status") not in statuses
                or (run["status"] == "completed" and run.get("conclusion") not in conclusions)
                or (run["status"] != "completed" and run.get("conclusion") is not None)):
            refuse("hosted workflow query returned a malformed or non-exact run")
    latest = max(exact, key=lambda run: (run["run_number"], run["run_attempt"], run["id"]))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        refuse("newest exact hosted validation workflow did not complete successfully")
    return latest["run_number"], latest["run_attempt"], latest["id"]


def verify_hosted_candidate(*, repository: RepositoryView, github: GitHubView,
                            candidate: dict[str, Any], now: dt.datetime | None) -> dict[str, Any]:
    commit, parent, artifact = candidate["commit"], candidate["parent"], candidate["artifact"]
    issued, start_by, _, _ = authorization_times(artifact, now=now)
    if repository.signature_fingerprint(commit) != WEB_FLOW_FINGERPRINT:
        refuse("authorization commit signer differs from pinned GitHub web-flow")
    committer, email, subject = repository.commit_metadata(commit)
    subject_match = re.search(r"\(#([1-9][0-9]*)\)$", subject)
    pr_number = artifact["pr_number"]
    if (committer != "GitHub" or email != "noreply@github.com" or subject_match is None
            or int(subject_match.group(1)) != pr_number):
        refuse("authorization commit is not the exact GitHub web-flow squash merge")
    pr = github.pull_request(pr_number)
    base, pr_head, merged_by = pr.get("base"), pr.get("head"), pr.get("merged_by")
    if not isinstance(base, dict) or not isinstance(pr_head, dict) or not isinstance(merged_by, dict):
        refuse("authorization PR metadata differs")
    base_repo, head_repo = base.get("repo"), pr_head.get("repo")
    if (pr.get("number") != pr_number or pr.get("state") != "closed" or pr.get("merged") is not True
            or pr.get("merge_commit_sha") != commit or base.get("ref") != "main" or base.get("sha") != parent
            or not isinstance(base_repo, dict) or base_repo.get("full_name") != REPOSITORY
            or not isinstance(head_repo, dict) or head_repo.get("full_name") != REPOSITORY
            or merged_by.get("login") != TRUSTED_MERGER or merged_by.get("type") != "User"
            or not isinstance(pr_head.get("sha"), str) or not COMMIT.fullmatch(pr_head["sha"])):
        refuse("authorization PR is not the exact trusted canonical merged source")
    merged_at = parse_timestamp(pr.get("merged_at"), "authorization PR merged_at")
    if merged_at < issued - dt.timedelta(seconds=30) or merged_at >= start_by:
        refuse("authorization issue/start window does not bind the merge time")
    pr_head_sha = pr_head["sha"]
    if github.commit_tree(pr_head_sha) != repository.tree_oid(commit):
        refuse("PR head tree differs from the signed squash authorization tree")
    return {"pr_number": pr_number, "pr_head_sha": pr_head_sha,
            "workflow": select_workflow(github, pr_head_sha, pr_number)}


def verify_authorization(*, repository: RepositoryView, github: GitHubView, operation_id: str,
                         binding: dict[str, Any], now: dt.datetime | None = None,
                         clock: Callable[[], dt.datetime] | None = None) -> dict[str, Any]:
    if now is not None and clock is not None:
        refuse("verification accepts one internal clock source")
    if clock is None:
        clock = (lambda: now) if now is not None else (lambda: dt.datetime.now(dt.timezone.utc))
    initial_now = utc(clock())
    validate_binding(binding, operation_id)
    relative = f"config/phase6-authorizations/{operation_id}-transaction.json"
    artifact_path = repository.root / pathlib.PurePosixPath(relative)
    if repository.origin() != ORIGIN or not repository.clean():
        refuse("authorization requires the exact canonical origin and clean worktree")
    head = repository.head()
    if not COMMIT.fullmatch(head) or github.main_head() != head:
        refuse("local authorization commit is not canonical remote main")
    artifact_bytes = repository.tracked_blob(head, relative)
    if artifact_path.is_symlink() or not artifact_path.is_file() or artifact_path.read_bytes() != artifact_bytes:
        refuse("worktree authorization is not the exact regular tracked blob")
    artifact = parse_object_bytes(artifact_bytes, "tracked transaction authorization")
    validate_binding(artifact, operation_id)
    if artifact != binding:
        refuse("tracked authorization differs from the local reviewed transaction binding")
    candidates = scan_authorization_history(repository, head)
    current = [candidate for candidate in candidates
               if candidate["commit"] == head and candidate["path"] == relative]
    if len(current) != 1 or current[0]["payload"] != artifact_bytes:
        refuse("current transaction authorization is absent from immutable append-only history")
    verify_governance(github)
    hosted: dict[str, Any] | None = None
    for candidate in candidates:
        checked = verify_hosted_candidate(
            repository=repository, github=github, candidate=candidate,
            now=initial_now if candidate["commit"] == head else None,
        )
        if candidate["commit"] == head:
            hosted = checked
    if hosted is None:
        refuse("current hosted transaction authorization was not verified")

    # A receipt is emitted only after a new clock sample and new remote queries.
    # A workflow rerun, main movement, local movement, or deadline crossing wins the race.
    final_now = utc(clock())
    _, start_by, complete_by, expiry = authorization_times(artifact, now=final_now)
    if not final_now < start_by < complete_by < expiry:
        refuse("transaction start boundary closed before verifier receipt")
    if repository.head() != head or not repository.clean() or github.main_head() != head:
        refuse("canonical main or clean local authorization commit changed before receipt")
    final_workflow = select_workflow(github, hosted["pr_head_sha"], hosted["pr_number"])
    if final_workflow != hosted["workflow"]:
        refuse("newest exact hosted workflow attempt changed before verifier receipt")

    history_sha256 = hashlib.sha256(json.dumps([
        {"commit": candidate["commit"], "path": candidate["path"],
         "authorization_sha256": hashlib.sha256(candidate["payload"]).hexdigest(),
         "operation_id": candidate["artifact"]["operation_id"],
         "operation_nonce": candidate["artifact"]["operation_nonce"]}
        for candidate in candidates
    ], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    return {
        "schema_version": 1, "status": "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT",
        "phase": 6, "authorization_mode": "TRANSACTION", "operation_id": operation_id,
        "authorization_commit": head, "authorization_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "authorization_history_sha256": history_sha256,
        "source_parent_commit": artifact["source_parent_commit"], "workflow_id": WORKFLOW_ID,
        "pr_number": hosted["pr_number"], "complete_by": artifact["complete_by"],
        "web_flow_fingerprint": WEB_FLOW_FINGERPRINT, "requires_reverification_before_use": True,
        "raw_values_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=pathlib.Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--binding", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        receipt = verify_authorization(repository=GitRepository(args.repository), github=GitHubAPI(),
                                       operation_id=args.operation_id,
                                       binding=read_object(args.binding, "local reviewed transaction binding"))
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except AuthorizationRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
