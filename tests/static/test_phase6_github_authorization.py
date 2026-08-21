#!/usr/bin/env python3
"""Credential-free behavioral tests for the dormant transaction verifier."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "verify-github-authorization.py"
SPEC = importlib.util.spec_from_file_location("phase6_github_transaction", SCRIPT)
assert SPEC and SPEC.loader
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)
NOW = dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.timezone.utc)
OPERATION = "0" * 64
HEAD = "a" * 40
PARENT = "b" * 40
TREE = "c" * 40
MANIFEST = "d" * 64
PR_HEAD = "e" * 40
HEAD_TREE = "f" * 40


def digest(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def artifact() -> dict:
    value = {
        "schema_version": 1, "phase": 6, "status": "GITHUB_PROTECTED_MAIN_AUTHORIZED",
        "authorization_mode": "TRANSACTION", "repository": AUTH.REPOSITORY,
        "workflow_id": AUTH.WORKFLOW_ID, "pr_number": 31, "source_parent_commit": PARENT,
        "source_tree_oid": TREE, "source_tree_manifest_sha256": MANIFEST,
        "operation_id": OPERATION, "operation_nonce": "f" * 64, "node": "03",
        "direction": "resize", "state_serial": 12, "security_approved": True,
        "reliability_approved": True, "approved_resource_expiry_utc": AUTH.APPROVED_EXPIRY,
        "journal_generation": 1, "journal_state": "AUTHORIZED",
        "approved_cost_ceiling_usd": AUTH.APPROVED_COST,
        "issued_at": "2026-08-21T11:30:00Z", "start_by": "2026-08-21T12:30:00Z",
        "raw_values_recorded": False,
    }
    for key in AUTH.DIGEST_KEYS - {"source_tree_manifest_sha256", "operation_id", "operation_nonce"}:
        value[key] = digest(key)
    return value


def governance() -> dict:
    return {
        "required_status_checks": {
            "strict": True, "contexts": [AUTH.WORKFLOW_CONTEXT],
            "checks": [{"context": AUTH.WORKFLOW_CONTEXT, "app_id": AUTH.WORKFLOW_APP_ID}],
        },
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {
            "required_approving_review_count": 0, "bypass_pull_request_allowances": {},
        },
        "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
        "required_linear_history": {"enabled": True}, "restrictions": None,
        "required_signatures": {"enabled": False},
    }


class FakeRepository:
    def __init__(self, root: pathlib.Path, value: dict) -> None:
        self.root = root
        self.relative = f"config/phase6-authorizations/{OPERATION}-transaction.json"
        path = root / pathlib.PurePosixPath(self.relative)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        self.blobs = {(HEAD, self.relative): path.read_bytes()}
        self.paths = [self.relative]
        self.origin_value = AUTH.ORIGIN
        self.clean_value = True
        self.head_value = HEAD
        self.parents_value = [PARENT]
        self.changed_value = [("A", self.relative)]
        self.parent_has_path = False
        self.tree_value = TREE
        self.manifest_value = MANIFEST
        self.signature_value = AUTH.WEB_FLOW_FINGERPRINT
        self.metadata_value = ("GitHub", "noreply@github.com", "ops: authorize transaction (#31)")

    def origin(self): return self.origin_value
    def clean(self): return self.clean_value
    def head(self): return self.head_value
    def parents(self, commit): return self.parents_value
    def changed_entries(self, parent, commit): return self.changed_value
    def path_exists(self, commit, path): return self.parent_has_path
    def tree_oid(self, commit): return HEAD_TREE if commit == HEAD else self.tree_value
    def tree_manifest_sha256(self, commit): return self.manifest_value
    def tracked_blob(self, commit, path): return self.blobs[(commit, path)]
    def tracked_paths(self, commit, prefix): return self.paths
    def commit_metadata(self, commit): return self.metadata_value
    def signature_fingerprint(self, commit): return self.signature_value


class FakeGitHub:
    def __init__(self) -> None:
        self.main_value = HEAD
        self.tree_value = HEAD_TREE
        self.protection = governance()
        self.settings = {
            "full_name": AUTH.REPOSITORY, "default_branch": "main", "allow_squash_merge": True,
            "allow_merge_commit": False, "allow_rebase_merge": False,
        }
        self.pr = {
            "number": 31, "state": "closed", "merged": True, "merge_commit_sha": HEAD,
            "merged_at": "2026-08-21T11:30:10Z",
            "merged_by": {"login": AUTH.TRUSTED_MERGER, "type": "User"},
            "base": {"ref": "main", "sha": PARENT, "repo": {"full_name": AUTH.REPOSITORY}},
            "head": {"sha": PR_HEAD, "repo": {"full_name": AUTH.REPOSITORY}},
        }
        self.runs = [{
            "workflow_id": AUTH.WORKFLOW_ID, "head_sha": PR_HEAD, "event": "pull_request",
            "status": "completed", "conclusion": "success", "path": AUTH.WORKFLOW_PATH,
            "head_repository": {"full_name": AUTH.REPOSITORY}, "run_number": 1,
            "run_attempt": 1, "id": 1, "pull_requests": [{"number": 31}],
        }]
        self.signatures_enabled = False

    def main_head(self): return self.main_value
    def commit_tree(self, commit): return self.tree_value
    def pull_request(self, number): return self.pr
    def workflow_runs(self, head_sha): return self.runs
    def branch_protection(self): return self.protection
    def repository_settings(self): return self.settings
    def required_signatures_enabled(self): return self.signatures_enabled


class TransactionVerifierTests(unittest.TestCase):
    def fixture(self, directory: str):
        value = artifact()
        return FakeRepository(pathlib.Path(directory), value), FakeGitHub(), value

    def verify(self, repository, github, value):
        return AUTH.verify_authorization(repository=repository, github=github,
                                         operation_id=OPERATION, binding=value, now=NOW)

    def rewrite(self, repository, value):
        path = repository.root / pathlib.PurePosixPath(repository.relative)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        repository.blobs[(HEAD, repository.relative)] = path.read_bytes()

    def test_exact_transaction_is_accepted_only_as_dormant_reverify_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory)
            receipt = self.verify(repository, github, value)
            self.assertEqual(receipt["status"], "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT")
            self.assertEqual(receipt["authorization_mode"], "TRANSACTION")
            self.assertIs(receipt["requires_reverification_before_use"], True)
            self.assertNotIn("operation_nonce", receipt)

    def test_exact_schema_digest_boolean_integer_and_review_distinctness(self):
        mutations = {
            "extra": lambda v: v.update(extra=True),
            "missing": lambda v: v.pop("broker_sha256"),
            "digest": lambda v: v.update(plan_sha256="bad"),
            "bool-int": lambda v: v.update(state_serial=True),
            "security": lambda v: v.update(security_approved=False),
            "same-review": lambda v: v.update(reliability_review_sha256=v["security_review_sha256"]),
            "same-nonce": lambda v: v.update(operation_nonce=v["user_approval_sha256"]),
            "cost": lambda v: v.update(approved_cost_ceiling_usd=70.46),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                mutate(value)
                self.rewrite(repository, value)
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_repository_commit_added_only_parent_and_signature_boundaries(self):
        changes = {
            "origin_value": "https://github.com/attacker/repo.git", "clean_value": False,
            "parents_value": [PARENT, "1" * 40], "changed_value": [("M", "x")],
            "parent_has_path": True, "tree_value": "2" * 40, "manifest_value": "3" * 64,
            "signature_value": "4" * 40,
            "metadata_value": ("Local", "local@example", "authorize (#31)"),
        }
        for name, bad in changes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                setattr(repository, name, bad)
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_immutable_head_nonce_scan_ignores_worktree_and_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory)
            prior = f"config/phase6-authorizations/{'9' * 64}-transaction.json"
            repository.paths.append(prior)
            repository.blobs[(HEAD, prior)] = json.dumps({"operation_nonce": value["operation_nonce"]}).encode()
            # No prior worktree file exists: the verifier must still scan immutable HEAD.
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "already used"):
                self.verify(repository, github, value)

    def test_binding_and_immutable_worktree_blob_tamper_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory)
            binding = copy.deepcopy(value); binding["plan_sha256"] = "9" * 64
            with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, binding)
            path = repository.root / pathlib.PurePosixPath(repository.relative)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_timestamps_are_exact_bounded_fresh_and_bind_merge(self):
        mutations = {
            "equal": ("2026-08-21T11:30:00Z", "2026-08-21T11:30:00Z"),
            "long": ("2026-08-21T11:00:00Z", "2026-08-21T12:00:01Z"),
            "expired": ("2026-08-21T11:00:00Z", "2026-08-21T12:00:00Z"),
            "format": ("2026-08-21T11:30:00+00:00", "2026-08-21T12:30:00Z"),
        }
        for name, (issued, start_by) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                value.update(issued_at=issued, start_by=start_by); self.rewrite(repository, value)
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory)
            github.pr["merged_at"] = "2026-08-21T11:00:00Z"
            with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_live_governance_all_material_fields_fail_closed(self):
        cases = {
            "strict": lambda p: p["required_status_checks"].update(strict=False),
            "context": lambda p: p["required_status_checks"].update(contexts=["other"]),
            "app": lambda p: p["required_status_checks"].update(checks=[{"context": AUTH.WORKFLOW_CONTEXT, "app_id": 1}]),
            "admins": lambda p: p["enforce_admins"].update(enabled=False),
            "pr-required": lambda p: p.update(required_pull_request_reviews=None),
            "approvals": lambda p: p["required_pull_request_reviews"].update(required_approving_review_count=1),
            "bypass": lambda p: p["required_pull_request_reviews"].update(bypass_pull_request_allowances={"users": [1]}),
            "force": lambda p: p["allow_force_pushes"].update(enabled=True),
            "delete": lambda p: p["allow_deletions"].update(enabled=True),
            "linear": lambda p: p["required_linear_history"].update(enabled=False),
            "restriction": lambda p: p.update(restrictions={"users": [1]}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                mutate(github.protection)
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory); github.signatures_enabled = True
            with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)
        settings = ("allow_squash_merge", "allow_merge_commit", "allow_rebase_merge")
        for key in settings:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                github.settings[key] = not github.settings[key]
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_pr_actor_identity_and_tree_fail_closed(self):
        cases = {
            "merged_by": {"login": "attacker", "type": "User"},
            "merge_commit_sha": "1" * 40, "merged": False,
        }
        for key, bad in cases.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory); github.pr[key] = bad
                with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)
        with tempfile.TemporaryDirectory() as directory:
            repository, github, value = self.fixture(directory); github.tree_value = "2" * 40
            with self.assertRaises(AUTH.AuthorizationRefused): self.verify(repository, github, value)

    def test_newest_exact_workflow_attempt_must_be_completed_success(self):
        for status, conclusion in (("in_progress", None), ("completed", "failure")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                repository, github, value = self.fixture(directory)
                newest = copy.deepcopy(github.runs[0]); newest.update(id=2, run_attempt=2, status=status, conclusion=conclusion)
                github.runs.append(newest)
                with self.assertRaisesRegex(AUTH.AuthorizationRefused, "newest"):
                    self.verify(repository, github, value)

    def test_workflow_pagination_uses_all_statuses_and_refuses_truncation(self):
        api = AUTH.GitHubAPI()
        calls = []
        def pages(path, query=None):
            calls.append(copy.deepcopy(query))
            page = int(query["page"])
            return {"total_count": 101, "workflow_runs": [{}] * (100 if page == 1 else 1)}
        with mock.patch.object(api, "_get", side_effect=pages):
            self.assertEqual(len(api.workflow_runs(PR_HEAD)), 101)
        self.assertNotIn("status", calls[0])
        with mock.patch.object(api, "_get", return_value={"total_count": 101, "workflow_runs": [{}]}):
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "truncated"): api.workflow_runs(PR_HEAD)

    def test_duplicate_and_nonfinite_json_refused(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.assertRaises(AUTH.AuthorizationRefused): AUTH.parse_object_bytes(payload, "test")

    def test_tool_environment_is_minimal_and_caller_git_values_are_removed(self):
        environment = {"PATH": "evil", "AWS_SECRET_ACCESS_KEY": "secret", "GIT_CONFIG_COUNT": "9",
                       "TEMP": "tmp", "SystemRoot": "root"}
        with mock.patch.dict(os.environ, environment, clear=True):
            result = AUTH.GitRepository._minimal_environment()
        self.assertNotIn("PATH", result); self.assertNotIn("AWS_SECRET_ACCESS_KEY", result)
        self.assertNotIn("GIT_CONFIG_COUNT", result); self.assertEqual(result["TEMP"], "tmp")
        self.assertEqual(result["GIT_CONFIG_NOSYSTEM"], "1")

    def test_git_commands_use_absolute_attested_binary_and_exact_safe_directory(self):
        repository = object.__new__(AUTH.GitRepository)
        repository.root = pathlib.Path("C:/exact/repo")
        repository.git = pathlib.Path("C:/Program Files/Git/cmd/git.exe")
        command = repository._base()
        self.assertTrue(pathlib.PureWindowsPath(command[0]).is_absolute())
        self.assertIn("safe.directory=C:/exact/repo", command)
        self.assertNotIn("*", command)

    @unittest.skipUnless(os.name == "nt", "pinned production toolchain is Windows-only")
    def test_pinned_space_containing_tools_verify_known_web_flow_signature(self):
        known = "ac58095f8feab8c3febdb091080acaefb9d0e82a"
        probe = subprocess.run([r"C:\Program Files\Git\cmd\git.exe", "-c",
                                f"safe.directory={ROOT.as_posix()}", "cat-file", "-e", known],
                               cwd=ROOT, capture_output=True)
        if probe.returncode:
            self.skipTest("known signed commit is not present in this checkout")
        repository = object.__new__(AUTH.GitRepository)
        repository.root = ROOT.resolve()
        repository.git = repository._attest_git()
        repository.gpg = repository._attest_gpg()
        self.assertIn("Program Files", str(repository.gpg))
        self.assertEqual(repository.signature_fingerprint(known), AUTH.WEB_FLOW_FINGERPRINT)

    def test_caller_selected_repository_root_is_rejected_before_tools_or_git(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "canonical checkout"):
                AUTH.GitRepository(pathlib.Path(directory))

    def test_pinned_key_provenance_and_schema_match_source_contract(self):
        provenance = json.loads((ROOT / "config/phase6-authorizations/github-web-flow-key.provenance.json").read_text())
        key = (ROOT / "config/phase6-authorizations/github-web-flow.gpg.asc").read_bytes()
        self.assertEqual(hashlib.sha256(key).hexdigest(), AUTH.WEB_FLOW_KEY_SHA256)
        self.assertEqual(provenance["accepted_primary_fingerprint"], AUTH.WEB_FLOW_FINGERPRINT)
        schema = json.loads((ROOT / "schemas/phase6-github-authorization.schema.json").read_text())
        self.assertEqual(set(schema["required"]), AUTH.AUTHORIZATION_KEYS)

    def test_no_staged_schema_or_mutation_consumer_was_reintroduced(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("--stage", source)
        self.assertNotIn("PREPARE", source)
        self.assertNotIn("execute_reviewed_apply", source)
        phase2 = (ROOT / "scripts/infra/phase2.ps1").read_text(encoding="utf-8")
        self.assertNotIn("phase6-resize-apply", phase2)


if __name__ == "__main__":
    unittest.main()
