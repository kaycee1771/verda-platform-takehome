#!/usr/bin/env python3
"""Verify a dormant Phase 6 authorization against canonical GitHub protected main.

This verifier is read-only. No Phase 6 mutation route consumes its receipt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol


REPOSITORY = "kaycee1771/verda-platform-takehome"
ORIGIN = "https://github.com/kaycee1771/verda-platform-takehome.git"
MAIN_REF = "refs/heads/main"
WORKFLOW_ID = 335664221
WORKFLOW_PATH = ".github/workflows/validate.yml"
WEB_FLOW_FINGERPRINT = "968479A1AFF927E37D1A566BB5690EEEBB952194"
WEB_FLOW_KEY_ID = "B5690EEEBB952194"
WEB_FLOW_KEY_SHA256 = "40ce89d21fb075092d256f9fbf62a1c19299d3282cb913d3e61d08235d0c491a"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
STAGES = {"PREPARE", "APPLY", "RECOVER"}
AUTHORIZATION_ENVELOPE_KEYS = {
    "schema_version", "phase", "status", "repository", "workflow_id", "pr_number",
    "source_parent_commit", "source_tree_oid", "source_tree_manifest_sha256",
    "operation_nonce", "issued_at", "expires_at",
}
COMMON_BINDING_KEYS = {
    "authorization_stage", "operation_id", "node", "direction", "plan_sha256",
    "plan_semantic_sha256", "state_lineage_sha256", "state_serial", "journal_sha256",
    "journal_generation", "journal_state", "approval_sha256", "preflight_sha256",
    "cost_sha256", "capacity_sha256", "collector_sha256", "tool_lock_sha256",
    "contract_sha256", "raw_values_recorded",
}
STAGE_BINDING_KEYS = {
    "PREPARE": set(),
    "APPLY": {
        "prepare_authorization_commit", "prepare_authorization_sha256", "prepare_sha256",
        "two_survivor_collector_sha256",
    },
    "RECOVER": {
        "apply_authorization_commit", "apply_authorization_sha256", "apply_receipt_sha256",
        "applied_state_lineage_sha256", "applied_state_serial", "host_key_provenance_sha256",
        "recovery_collector_sha256", "inventory_sha256", "known_hosts_sha256",
    },
}
COMMON_DIGEST_BINDINGS = {
    "operation_id", "plan_sha256", "plan_semantic_sha256", "state_lineage_sha256",
    "journal_sha256", "approval_sha256", "preflight_sha256", "cost_sha256",
    "capacity_sha256", "collector_sha256", "tool_lock_sha256", "contract_sha256",
}
STAGE_DIGEST_BINDINGS = {
    "PREPARE": set(),
    "APPLY": {"prepare_authorization_sha256", "prepare_sha256", "two_survivor_collector_sha256"},
    "RECOVER": {
        "apply_authorization_sha256", "apply_receipt_sha256", "applied_state_lineage_sha256",
        "host_key_provenance_sha256", "recovery_collector_sha256", "inventory_sha256",
        "known_hosts_sha256",
    },
}


def binding_keys(stage: str) -> set[str]:
    return COMMON_BINDING_KEYS | STAGE_BINDING_KEYS[stage]


def authorization_keys(stage: str) -> set[str]:
    return AUTHORIZATION_ENVELOPE_KEYS | binding_keys(stage)


def digest_bindings(stage: str) -> set[str]:
    return COMMON_DIGEST_BINDINGS | STAGE_DIGEST_BINDINGS[stage]


class AuthorizationRefused(ValueError):
    pass


def refuse(message: str) -> None:
    raise AuthorizationRefused(message)


def read_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        return parse_object_bytes(path.read_bytes(), label)
    except OSError as error:
        refuse(f"{label} is unreadable: {type(error).__name__}")


def parse_object_bytes(payload: bytes, label: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                refuse(f"{label} contains a duplicate JSON field")
            value[key] = item
        return value

    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=lambda _: refuse(f"{label} contains a non-finite JSON number"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        refuse(f"{label} is unreadable: {type(error).__name__}")
    if not isinstance(value, dict):
        refuse(f"{label} is not one JSON object")
    return value


def parse_timestamp(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str):
        refuse(f"{label} is not a timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        refuse(f"{label} is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        refuse(f"{label} is not an exact UTC timestamp")
    return parsed.astimezone(dt.timezone.utc)


class RepositoryView(Protocol):
    root: pathlib.Path

    def origin(self) -> str: ...
    def clean(self) -> bool: ...
    def head(self) -> str: ...
    def parents(self, commit: str) -> list[str]: ...
    def changed_paths(self, parent: str, commit: str) -> list[str]: ...
    def tree_oid(self, commit: str) -> str: ...
    def tree_manifest_sha256(self, commit: str) -> str: ...
    def tracked_blob(self, commit: str, path: str) -> bytes: ...
    def commit_metadata(self, commit: str) -> tuple[str, str, str]: ...
    def signature_fingerprint(self, commit: str) -> str: ...


class GitRepository:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root.resolve(strict=True)

    @staticmethod
    def _environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
        })
        if extra:
            environment.update(extra)
        return environment

    def _run(self, arguments: list[str], *, text: bool = True, env: dict[str, str] | None = None) -> Any:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", *arguments],
            cwd=self.root, check=False, capture_output=True, text=text,
            env=self._environment(env),
        )
        if result.returncode != 0:
            refuse("canonical Git repository verification failed")
        return result.stdout

    def origin(self) -> str:
        return self._run(["remote", "get-url", "origin"]).strip()

    def clean(self) -> bool:
        return not self._run(["status", "--porcelain=v2", "--untracked-files=all"]).strip()

    def head(self) -> str:
        return self._run(["rev-parse", "HEAD"]).strip()

    def parents(self, commit: str) -> list[str]:
        values = self._run(["rev-list", "--parents", "-n", "1", commit]).strip().split()
        return values[1:]

    def changed_paths(self, parent: str, commit: str) -> list[str]:
        raw = self._run(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", parent, commit], text=False,
        )
        return [item.decode("utf-8") for item in raw.split(b"\0") if item]

    def tree_oid(self, commit: str) -> str:
        return self._run(["rev-parse", f"{commit}^{{tree}}"]).strip()

    def tree_manifest_sha256(self, commit: str) -> str:
        raw = self._run(["ls-tree", "-r", "-z", "--full-tree", commit], text=False)
        return hashlib.sha256(raw).hexdigest()

    def tracked_blob(self, commit: str, path: str) -> bytes:
        if path.startswith("/") or ".." in pathlib.PurePosixPath(path).parts:
            refuse("tracked authorization path is invalid")
        return self._run(["show", f"{commit}:{path}"], text=False)

    def commit_metadata(self, commit: str) -> tuple[str, str, str]:
        raw = self._run(["show", "-s", "--format=%cn%x00%ce%x00%s", commit], text=False)
        parts = raw.rstrip(b"\n").split(b"\0")
        if len(parts) != 3:
            refuse("authorization commit metadata differs")
        return tuple(part.decode("utf-8") for part in parts)  # type: ignore[return-value]

    @staticmethod
    def _gpg() -> str:
        found = shutil.which("gpg")
        if found:
            return found
        git = shutil.which("git")
        if git and os.name == "nt":
            bundled = pathlib.Path(git).resolve().parents[1] / "usr" / "bin" / "gpg.exe"
            if bundled.is_file():
                return str(bundled)
        refuse("pinned OpenPGP verifier is unavailable")

    def signature_fingerprint(self, commit: str) -> str:
        key = self.root / "config" / "phase6-authorizations" / "github-web-flow.gpg.asc"
        provenance = read_object(
            self.root / "config" / "phase6-authorizations" / "github-web-flow-key.provenance.json",
            "web-flow key provenance",
        )
        if hashlib.sha256(key.read_bytes()).hexdigest() != WEB_FLOW_KEY_SHA256:
            refuse("vendored web-flow key digest differs")
        if provenance != {
            "schema_version": 1,
            "source": "https://api.github.com/users/web-flow/gpg_keys",
            "raw_endpoint": "https://github.com/web-flow.gpg",
            "api_record_id": 3040729,
            "retrieval_date_utc": "2026-08-21",
            "armored_sha256": WEB_FLOW_KEY_SHA256,
            "accepted_primary_fingerprint": WEB_FLOW_FINGERPRINT,
            "accepted_key_id": WEB_FLOW_KEY_ID,
            "accepted_uid": "GitHub <noreply@github.com>",
            "raw_values_recorded": False,
        }:
            refuse("vendored web-flow key provenance differs")
        gpg = self._gpg()
        with tempfile.TemporaryDirectory(prefix="phase6-web-flow-") as home:
            environment = self._environment({"GNUPGHOME": home})
            imported = subprocess.run(
                [gpg, "--batch", "--import", str(key)], check=False, capture_output=True, env=environment,
            )
            fingerprints = subprocess.run(
                [gpg, "--batch", "--with-colons", "--fingerprint"], check=False,
                capture_output=True, text=True, env=environment,
            )
            if (
                imported.returncode not in {0, 2} or fingerprints.returncode != 0
                or f"fpr:::::::::{WEB_FLOW_FINGERPRINT}:" not in fingerprints.stdout
            ):
                refuse("vendored web-flow key fingerprint differs")
            verified = subprocess.run(
                ["git", "--no-replace-objects", "-c", f"gpg.program={gpg}", "verify-commit", "--raw", commit],
                cwd=self.root, check=False, capture_output=True, text=True, env=environment,
            )
            status = verified.stderr + verified.stdout
            match = re.search(r"\[GNUPG:\] VALIDSIG ([0-9A-F]{40}) ", status)
            if verified.returncode != 0 or match is None:
                refuse("authorization commit lacks a valid pinned web-flow signature")
            return match.group(1)


class GitHubView(Protocol):
    def main_head(self) -> str: ...
    def commit_tree(self, commit: str) -> str: ...
    def pull_request(self, number: int) -> dict[str, Any]: ...
    def workflow_runs(self, head_sha: str) -> list[dict[str, Any]]: ...


class GitHubAPI:
    def _get(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{REPOSITORY}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json", "User-Agent": "verda-phase6-auth-v1"},
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            )
            with opener.open(request, timeout=20) as response:
                value = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            refuse("canonical GitHub metadata verification failed")
        if not isinstance(value, dict):
            refuse("canonical GitHub metadata response differs")
        return value

    def pull_request(self, number: int) -> dict[str, Any]:
        return self._get(f"pulls/{number}")

    def main_head(self) -> str:
        value = self._get("git/ref/heads/main")
        target = value.get("object")
        if (
            value.get("ref") != MAIN_REF or not isinstance(target, dict)
            or target.get("type") != "commit" or not isinstance(target.get("sha"), str)
            or not COMMIT.fullmatch(target["sha"])
        ):
            refuse("canonical GitHub main reference differs")
        return target["sha"]

    def commit_tree(self, commit: str) -> str:
        if not COMMIT.fullmatch(commit):
            refuse("canonical GitHub commit identity differs")
        value = self._get(f"git/commits/{commit}")
        tree = value.get("tree")
        if not isinstance(tree, dict) or not isinstance(tree.get("sha"), str) or not COMMIT.fullmatch(tree["sha"]):
            refuse("canonical GitHub commit tree differs")
        return tree["sha"]

    def workflow_runs(self, head_sha: str) -> list[dict[str, Any]]:
        value = self._get(
            f"actions/workflows/{WORKFLOW_ID}/runs",
            {"event": "pull_request", "head_sha": head_sha, "status": "completed", "per_page": "100"},
        )
        runs = value.get("workflow_runs")
        if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
            refuse("canonical GitHub workflow response differs")
        return runs


def validate_binding(binding: dict[str, Any], operation_id: str, stage: str) -> None:
    if stage not in STAGES or binding.get("authorization_stage") != stage:
        refuse("authorization stage differs")
    if set(binding) != binding_keys(stage):
        refuse("local reviewed binding schema differs")
    if binding.get("operation_id") != operation_id or not DIGEST.fullmatch(operation_id):
        refuse("operation identity differs")
    if binding.get("node") not in {"01", "02", "03"} or binding.get("direction") not in {"resize", "rollback"}:
        refuse("operation target differs")
    if any(
        not isinstance(binding.get(key), str) or not DIGEST.fullmatch(binding[key])
        for key in digest_bindings(stage)
    ):
        refuse("reviewed binding digest differs")
    for key in STAGE_BINDING_KEYS[stage] & {"prepare_authorization_commit", "apply_authorization_commit"}:
        if not isinstance(binding.get(key), str) or not COMMIT.fullmatch(binding[key]):
            refuse("prior authorization commit binding differs")
    expected_journal_state = "APPLIED" if stage == "RECOVER" else "PREPARED"
    if (
        type(binding.get("state_serial")) is not int or binding["state_serial"] < 0
        or type(binding.get("journal_generation")) is not int or binding["journal_generation"] < 1
        or binding.get("journal_state") != expected_journal_state
        or binding.get("raw_values_recorded") is not False
    ):
        refuse("reviewed state/journal boundary differs")
    if stage == "RECOVER" and (
        type(binding.get("applied_state_serial")) is not int
        or binding["applied_state_serial"] <= binding["state_serial"]
    ):
        refuse("applied state serial binding differs")


def verify_authorization(
    *, repository: RepositoryView, github: GitHubView, operation_id: str,
    stage: str, binding: dict[str, Any], now: dt.datetime,
) -> dict[str, Any]:
    validate_binding(binding, operation_id, stage)
    stage_name = stage.lower()
    relative = f"config/phase6-authorizations/{operation_id}-{stage_name}.json"
    artifact_path = repository.root / pathlib.PurePosixPath(relative)
    if repository.origin() != ORIGIN or not repository.clean():
        refuse("authorization requires the exact canonical origin and clean worktree")
    head = repository.head()
    if not COMMIT.fullmatch(head) or github.main_head() != head:
        refuse("local authorization commit is not canonical remote main")
    artifact_bytes = repository.tracked_blob(head, relative)
    if artifact_path.is_symlink() or not artifact_path.is_file() or artifact_path.read_bytes() != artifact_bytes:
        refuse("worktree authorization is not the exact regular tracked blob")
    artifact = parse_object_bytes(artifact_bytes, "tracked operation authorization")
    if set(artifact) != authorization_keys(stage):
        refuse("tracked operation authorization schema differs")
    fixed = {
        "schema_version": 1, "phase": 6, "status": "GITHUB_PROTECTED_MAIN_AUTHORIZED",
        "repository": REPOSITORY, "workflow_id": WORKFLOW_ID, "operation_id": operation_id,
        "authorization_stage": stage,
        "journal_state": "APPLIED" if stage == "RECOVER" else "PREPARED",
        "raw_values_recorded": False,
    }
    if any(artifact.get(key) != value for key, value in fixed.items()):
        refuse("tracked operation authorization identity differs")
    if any(artifact.get(key) != value for key, value in binding.items()):
        refuse("tracked authorization differs from the local reviewed binding")
    for key in ("source_tree_manifest_sha256", "operation_nonce"):
        if not isinstance(artifact.get(key), str) or not DIGEST.fullmatch(artifact[key]):
            refuse("tracked source-tree or nonce digest differs")
    for key in ("source_parent_commit", "source_tree_oid"):
        if not isinstance(artifact.get(key), str) or not COMMIT.fullmatch(artifact[key]):
            refuse("tracked source commit/tree identity differs")
    nonce = artifact["operation_nonce"]
    digest_values = {artifact[key] for key in digest_bindings(stage)} | {artifact["source_tree_manifest_sha256"]}
    if nonce in digest_values:
        refuse("operation nonce is not independently generated")
    for candidate in sorted(artifact_path.parent.glob("[0-9a-f]" * 64 + "-*.json")):
        if candidate != artifact_path:
            candidate_relative = candidate.relative_to(repository.root).as_posix()
            if candidate.is_symlink() or not candidate.is_file():
                refuse("prior tracked operation authorization is not a regular file")
            other_bytes = repository.tracked_blob(head, candidate_relative)
            if candidate.read_bytes() != other_bytes:
                refuse("prior tracked operation authorization differs from its tracked blob")
            other = parse_object_bytes(other_bytes, "prior tracked operation authorization")
            if other.get("operation_nonce") == nonce:
                refuse("operation nonce was already used by another tracked authorization")
    issued = parse_timestamp(artifact.get("issued_at"), "authorization issued_at")
    expires = parse_timestamp(artifact.get("expires_at"), "authorization expires_at")
    utc_now = now.astimezone(dt.timezone.utc)
    if issued > utc_now + dt.timedelta(seconds=30) or expires <= utc_now or expires - issued > dt.timedelta(hours=1):
        refuse("tracked authorization is stale, future-dated, or exceeds one hour")

    parent = artifact["source_parent_commit"]
    if repository.parents(head) != [parent]:
        refuse("authorization commit is not a one-parent squash commit over the bound source")
    if repository.changed_paths(parent, head) != [relative]:
        refuse("authorization commit changed files beyond the exact operation artifact")
    if repository.tree_oid(parent) != artifact["source_tree_oid"]:
        refuse("authorization source tree object differs")
    if repository.tree_manifest_sha256(parent) != artifact["source_tree_manifest_sha256"]:
        refuse("authorization source tree manifest differs")
    prior_stage = {"APPLY": "prepare", "RECOVER": "apply"}.get(stage)
    if prior_stage is not None:
        commit_key = f"{prior_stage}_authorization_commit"
        digest_key = f"{prior_stage}_authorization_sha256"
        if artifact[commit_key] != parent:
            refuse("staged authorization does not directly follow its bound prior authorization")
        prior_relative = f"config/phase6-authorizations/{operation_id}-{prior_stage}.json"
        prior_bytes = repository.tracked_blob(parent, prior_relative)
        if hashlib.sha256(prior_bytes).hexdigest() != artifact[digest_key]:
            refuse("prior staged authorization digest differs from the bound parent blob")
        prior = parse_object_bytes(prior_bytes, "prior staged authorization")
        if (
            prior.get("operation_id") != operation_id
            or prior.get("authorization_stage") != prior_stage.upper()
            or prior.get("node") != artifact["node"] or prior.get("direction") != artifact["direction"]
        ):
            refuse("prior staged authorization identity differs")
    if repository.signature_fingerprint(head) != WEB_FLOW_FINGERPRINT:
        refuse("authorization commit signer differs from pinned GitHub web-flow")
    committer, email, subject = repository.commit_metadata(head)
    subject_match = re.search(r"\(#([1-9][0-9]*)\)$", subject)
    if committer != "GitHub" or email != "noreply@github.com" or subject_match is None:
        refuse("authorization commit is not an exact GitHub web-flow squash merge")
    pr_number = artifact.get("pr_number")
    if type(pr_number) is not int or pr_number < 1 or int(subject_match.group(1)) != pr_number:
        refuse("authorization PR identity differs from the signed squash subject")

    pr = github.pull_request(pr_number)
    base, pr_head = pr.get("base"), pr.get("head")
    if not isinstance(base, dict) or not isinstance(pr_head, dict):
        refuse("authorization PR metadata differs")
    base_repo, head_repo = base.get("repo"), pr_head.get("repo")
    if (
        pr.get("number") != pr_number or pr.get("state") != "closed" or pr.get("merged") is not True
        or pr.get("merge_commit_sha") != head or base.get("ref") != "main" or base.get("sha") != parent
        or not isinstance(base_repo, dict) or base_repo.get("full_name") != REPOSITORY
        or not isinstance(head_repo, dict) or head_repo.get("full_name") != REPOSITORY
        or not isinstance(pr_head.get("sha"), str) or not COMMIT.fullmatch(pr_head["sha"])
    ):
        refuse("authorization PR is not the exact canonical merged source")
    pr_head_sha = pr_head["sha"]
    if github.commit_tree(pr_head_sha) != repository.tree_oid(head):
        refuse("PR head tree differs from the signed squash authorization tree")
    matching_runs = [
        run for run in github.workflow_runs(pr_head_sha)
        if run.get("workflow_id") == WORKFLOW_ID and run.get("head_sha") == pr_head_sha
        and run.get("event") == "pull_request" and run.get("status") == "completed"
        and run.get("path") == WORKFLOW_PATH
        and isinstance(run.get("head_repository"), dict)
        and run["head_repository"].get("full_name") == REPOSITORY
        and isinstance(run.get("pull_requests"), list)
        and any(isinstance(item, dict) and item.get("number") == pr_number for item in run["pull_requests"])
    ]
    if not matching_runs:
        refuse("exact hosted validation workflow did not run on the PR head")
    latest = max(
        matching_runs,
        key=lambda run: tuple(run.get(key) if isinstance(run.get(key), int) else -1 for key in (
            "run_number", "run_attempt", "id",
        )),
    )
    if latest.get("conclusion") != "success":
        refuse("exact hosted validation workflow did not pass on the PR head")

    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    return {
        "schema_version": 1, "status": "GITHUB_AUTHORIZATION_VERIFIED_DORMANT",
        "phase": 6, "authorization_stage": stage, "operation_id": operation_id,
        "authorization_commit": head,
        "authorization_sha256": artifact_sha256, "source_parent_commit": parent,
        "workflow_id": WORKFLOW_ID, "pr_number": pr_number,
        "web_flow_fingerprint": WEB_FLOW_FINGERPRINT, "raw_values_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=pathlib.Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    parser.add_argument("--binding", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        receipt = verify_authorization(
            repository=GitRepository(args.repository), github=GitHubAPI(), operation_id=args.operation_id,
            stage=args.stage, binding=read_object(args.binding, "local reviewed binding"),
            now=dt.datetime.now(dt.timezone.utc),
        )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except AuthorizationRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
