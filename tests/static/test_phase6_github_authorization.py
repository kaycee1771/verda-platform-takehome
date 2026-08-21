#!/usr/bin/env python3
"""Credential-free behavioral tests for the dormant GitHub authorization verifier."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "verify-github-authorization.py"
SPEC = importlib.util.spec_from_file_location("phase6_github_authorization", SCRIPT)
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


def binding(stage: str = "PREPARE") -> dict:
    value = {
        "authorization_stage": stage, "operation_id": OPERATION, "node": "03", "direction": "resize",
        "state_serial": 12, "journal_generation": 1,
        "journal_state": "APPLIED" if stage == "RECOVER" else "PREPARED",
        "raw_values_recorded": False,
    }
    for key in sorted(AUTH.digest_bindings(stage) - {"operation_id"}):
        value[key] = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if stage == "APPLY":
        value["prepare_authorization_commit"] = PARENT
    elif stage == "RECOVER":
        value["apply_authorization_commit"] = PARENT
        value["applied_state_serial"] = 13
    return value


def artifact(reviewed: dict) -> dict:
    return {
        "schema_version": 1, "phase": 6, "status": "GITHUB_PROTECTED_MAIN_AUTHORIZED",
        "repository": AUTH.REPOSITORY, "workflow_id": AUTH.WORKFLOW_ID, "pr_number": 31,
        "source_parent_commit": PARENT, "source_tree_oid": TREE,
        "source_tree_manifest_sha256": MANIFEST, "operation_nonce": "f" * 64,
        "issued_at": "2026-08-21T11:30:00Z", "expires_at": "2026-08-21T12:30:00Z",
        **reviewed,
    }


class FakeRepository:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.origin_value = AUTH.ORIGIN
        self.clean_value = True
        self.head_value = HEAD
        self.parents_value = [PARENT]
        self.changed_value = [f"config/phase6-authorizations/{OPERATION}-prepare.json"]
        self.tree_value = TREE
        self.manifest_value = MANIFEST
        self.metadata_value = ("GitHub", "noreply@github.com", "ops(phase6): authorize node 03 (#31)")
        self.signature_value = AUTH.WEB_FLOW_FINGERPRINT

    def origin(self) -> str: return self.origin_value
    def clean(self) -> bool: return self.clean_value
    def head(self) -> str: return self.head_value
    def parents(self, commit: str) -> list[str]: return self.parents_value
    def changed_paths(self, parent: str, commit: str) -> list[str]: return self.changed_value
    def tree_oid(self, commit: str) -> str: return HEAD_TREE if commit == HEAD else self.tree_value
    def tree_manifest_sha256(self, commit: str) -> str: return self.manifest_value
    def tracked_blob(self, commit: str, path: str) -> bytes: return (self.root / pathlib.PurePosixPath(path)).read_bytes()
    def commit_metadata(self, commit: str) -> tuple[str, str, str]: return self.metadata_value
    def signature_fingerprint(self, commit: str) -> str: return self.signature_value


class FakeGitHub:
    def __init__(self) -> None:
        self.main_value = HEAD
        self.commit_tree_value = HEAD_TREE
        self.pr = {
            "number": 31, "state": "closed", "merged": True, "merge_commit_sha": HEAD,
            "base": {"ref": "main", "sha": PARENT, "repo": {"full_name": AUTH.REPOSITORY}},
            "head": {"sha": PR_HEAD, "repo": {"full_name": AUTH.REPOSITORY}},
        }
        self.runs = [{
            "workflow_id": AUTH.WORKFLOW_ID, "head_sha": PR_HEAD, "event": "pull_request",
            "status": "completed", "conclusion": "success", "path": AUTH.WORKFLOW_PATH,
            "head_repository": {"full_name": AUTH.REPOSITORY}, "run_number": 1,
            "run_attempt": 1, "id": 1, "pull_requests": [{"number": 31}],
        }]

    def main_head(self) -> str: return self.main_value
    def commit_tree(self, commit: str) -> str: return self.commit_tree_value
    def pull_request(self, number: int) -> dict: return self.pr
    def workflow_runs(self, head_sha: str) -> list[dict]: return self.runs


class GitHubAuthorizationTests(unittest.TestCase):
    def fixture(
        self, directory: str, stage: str = "PREPARE",
    ) -> tuple[FakeRepository, FakeGitHub, dict, dict, pathlib.Path]:
        root = pathlib.Path(directory)
        auth_dir = root / "config" / "phase6-authorizations"
        auth_dir.mkdir(parents=True)
        reviewed = binding(stage)
        authorized = artifact(reviewed)
        path = auth_dir / f"{OPERATION}-{stage.lower()}.json"
        path.write_text(json.dumps(authorized), encoding="utf-8")
        repository = FakeRepository(root)
        repository.changed_value = [path.relative_to(root).as_posix()]
        prior_stage = {"APPLY": "prepare", "RECOVER": "apply"}.get(stage)
        if prior_stage:
            prior = auth_dir / f"{OPERATION}-{prior_stage}.json"
            prior.write_text(json.dumps({
                "operation_id": OPERATION, "authorization_stage": prior_stage.upper(),
                "node": "03", "direction": "resize", "operation_nonce": "7" * 64,
            }), encoding="utf-8")
            reviewed[f"{prior_stage}_authorization_sha256"] = hashlib.sha256(prior.read_bytes()).hexdigest()
            authorized[f"{prior_stage}_authorization_sha256"] = reviewed[f"{prior_stage}_authorization_sha256"]
            path.write_text(json.dumps(authorized), encoding="utf-8")
        return repository, FakeGitHub(), reviewed, authorized, path

    def verify(
        self, repository: FakeRepository, github: FakeGitHub, reviewed: dict, stage: str = "PREPARE",
    ) -> dict:
        return AUTH.verify_authorization(
            repository=repository, github=github, operation_id=OPERATION,
            stage=stage, binding=reviewed, now=NOW,
        )

    def test_exact_fake_github_protected_main_boundary_is_accepted_dormant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, github, reviewed, _, _ = self.fixture(directory)
            receipt = self.verify(repository, github, reviewed)
            self.assertEqual(receipt["status"], "GITHUB_AUTHORIZATION_VERIFIED_DORMANT")
            self.assertEqual(receipt["authorization_commit"], HEAD)
            self.assertFalse(receipt["raw_values_recorded"])

    def test_prepare_apply_recover_capabilities_are_separate_and_chain_exactly(self) -> None:
        for stage in ("PREPARE", "APPLY", "RECOVER"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                repository, github, reviewed, authorized, _ = self.fixture(directory, stage)
                receipt = self.verify(repository, github, reviewed, stage)
                self.assertEqual(receipt["authorization_stage"], stage)
                if stage == "PREPARE":
                    self.assertNotIn("prepare_sha256", authorized)
                elif stage == "APPLY":
                    self.assertIn("prepare_sha256", authorized)
                    self.assertNotIn("apply_receipt_sha256", authorized)
                else:
                    self.assertIn("apply_receipt_sha256", authorized)
        with tempfile.TemporaryDirectory() as directory:
            repository, github, reviewed, authorized, path = self.fixture(directory, "APPLY")
            authorized["prepare_authorization_commit"] = "1" * 40
            reviewed["prepare_authorization_commit"] = "1" * 40
            path.write_text(json.dumps(authorized), encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "directly follow"):
                self.verify(repository, github, reviewed, "APPLY")

    def test_repository_commit_and_signature_mismatches_fail_closed(self) -> None:
        cases = {
            "origin_value": "https://github.com/attacker/repo.git",
            "clean_value": False,
            "parents_value": [PARENT, "2" * 40],
            "changed_value": [f"config/phase6-authorizations/{OPERATION}.json", "scripts/phase6/evil.py"],
            "tree_value": "3" * 40,
            "manifest_value": "4" * 64,
            "signature_value": "5" * 40,
            "metadata_value": ("Local User", "local@example.invalid", "authorize (#31)"),
        }
        for attribute, bad in cases.items():
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory() as directory:
                repository, github, reviewed, _, _ = self.fixture(directory)
                setattr(repository, attribute, bad)
                with self.assertRaises(AUTH.AuthorizationRefused):
                    self.verify(repository, github, reviewed)

    def test_canonical_github_main_and_used_nonce_mismatches_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, github, reviewed, authorized, path = self.fixture(directory)
            github.main_value = "1" * 40
            with self.assertRaises(AUTH.AuthorizationRefused):
                self.verify(repository, github, reviewed)
            github.main_value = HEAD
            prior = path.parent / f"{'9' * 64}-prepare.json"
            prior.write_text(json.dumps({"operation_nonce": authorized["operation_nonce"]}), encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "already used"):
                self.verify(repository, github, reviewed)

    def test_artifact_schema_binding_nonce_and_freshness_mismatches_fail_closed(self) -> None:
        changes = {
            "extra": lambda value, reviewed: value.update({"unexpected": True}),
            "binding": lambda value, reviewed: value.update({"plan_sha256": "0" * 64}),
            "nonce": lambda value, reviewed: value.update({"operation_nonce": reviewed["plan_sha256"]}),
            "stale": lambda value, reviewed: value.update({"expires_at": "2026-08-21T11:59:59Z"}),
            "long": lambda value, reviewed: value.update({"expires_at": "2026-08-21T13:00:01Z"}),
            "workflow": lambda value, reviewed: value.update({"workflow_id": 1}),
        }
        for name, mutate in changes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                repository, github, reviewed, authorized, path = self.fixture(directory)
                mutate(authorized, reviewed)
                path.write_text(json.dumps(authorized), encoding="utf-8")
                with self.assertRaises(AUTH.AuthorizationRefused):
                    self.verify(repository, github, reviewed)

    def test_boolean_integer_and_duplicate_json_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, github, reviewed, _, _ = self.fixture(directory)
            reviewed["state_serial"] = True
            with self.assertRaises(AUTH.AuthorizationRefused):
                self.verify(repository, github, reviewed)
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "duplicate JSON field"):
                AUTH.parse_object_bytes(b'{"phase":6,"phase":6}', "duplicate fixture")

    def test_pr_and_workflow_mismatches_fail_closed(self) -> None:
        cases = (
            "merge", "base", "head_repo", "head_tree", "workflow", "workflow_head",
            "workflow_path", "workflow_pr",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                repository, github, reviewed, _, _ = self.fixture(directory)
                if case == "merge": github.pr["merge_commit_sha"] = "1" * 40
                elif case == "base": github.pr["base"]["sha"] = "2" * 40
                elif case == "head_repo": github.pr["head"]["repo"]["full_name"] = "attacker/fork"
                elif case == "head_tree": github.commit_tree_value = "4" * 40
                elif case == "workflow": github.runs[0]["conclusion"] = "failure"
                elif case == "workflow_head": github.runs[0]["head_sha"] = "3" * 40
                elif case == "workflow_path": github.runs[0]["path"] = ".github/workflows/other.yml"
                else: github.runs[0]["pull_requests"] = [{"number": 99}]
                with self.assertRaises(AUTH.AuthorizationRefused):
                    self.verify(repository, github, reviewed)

    def test_latest_matching_workflow_attempt_must_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, github, reviewed, _, _ = self.fixture(directory)
            github.runs.append({**github.runs[0], "run_attempt": 2, "id": 2, "conclusion": "failure"})
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "did not pass"):
                self.verify(repository, github, reviewed)

    def test_vendored_key_and_provenance_are_exactly_pinned(self) -> None:
        key = ROOT / "config" / "phase6-authorizations" / "github-web-flow.gpg.asc"
        provenance = json.loads((key.parent / "github-web-flow-key.provenance.json").read_text())
        self.assertEqual(hashlib.sha256(key.read_bytes()).hexdigest(), AUTH.WEB_FLOW_KEY_SHA256)
        self.assertEqual(provenance["accepted_primary_fingerprint"], AUTH.WEB_FLOW_FINGERPRINT)
        self.assertEqual(provenance["accepted_key_id"], AUTH.WEB_FLOW_KEY_ID)

    def test_real_vendored_key_verifies_known_web_flow_commit_when_available(self) -> None:
        known_commit = "ac58095f8feab8c3febdb091080acaefb9d0e82a"
        present = __import__("subprocess").run(
            ["git", "cat-file", "-e", f"{known_commit}^{{commit}}"], cwd=ROOT, check=False,
            capture_output=True,
        )
        if present.returncode != 0:
            self.skipTest("known signed GitHub squash commit is absent from this checkout")
        self.assertEqual(AUTH.GitRepository(ROOT).signature_fingerprint(known_commit), AUTH.WEB_FLOW_FINGERPRINT)

    @unittest.skipUnless(AUTH.os.name == "nt", "Windows bundled Git path regression")
    def test_space_containing_bundled_gpg_path_is_posix_normalized_for_git_config(self) -> None:
        git = pathlib.Path("C:/Program Files/Git/cmd/git.exe")
        with mock.patch.object(AUTH.shutil, "which", side_effect=lambda name: None if name == "gpg" else str(git)), \
             mock.patch.object(AUTH.pathlib.Path, "is_file", return_value=True):
            gpg = AUTH.GitRepository._gpg()
        self.assertEqual(gpg, "C:/Program Files/Git/usr/bin/gpg.exe")
        self.assertNotIn("\\", gpg)

    def test_git_commands_pin_only_the_verifiers_exact_safe_directory(self) -> None:
        repository = AUTH.GitRepository(ROOT)
        completed = __import__("subprocess").CompletedProcess([], 0, stdout="ok\n", stderr="")
        with mock.patch.object(AUTH.subprocess, "run", return_value=completed) as invoked:
            self.assertEqual(repository._run(["rev-parse", "HEAD"]), "ok\n")
        command = invoked.call_args.args[0]
        self.assertIn(f"safe.directory={ROOT.resolve().as_posix()}", command)
        self.assertNotIn("safe.directory=*", command)
        environment = invoked.call_args.kwargs["env"]
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], AUTH.os.devnull)

    def test_alternate_or_symlinked_repository_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "exact canonical checkout"):
                AUTH.GitRepository(pathlib.Path(directory))
            link = pathlib.Path(directory) / "repo-link"
            try:
                link.symlink_to(ROOT, target_is_directory=True)
            except OSError:
                return
            with self.assertRaisesRegex(AUTH.AuthorizationRefused, "exact canonical checkout"):
                AUTH.GitRepository(link)

    def test_schema_and_readme_keep_authorization_dormant(self) -> None:
        schema = json.loads((ROOT / "schemas" / "phase6-github-authorization.schema.json").read_text())
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]), AUTH.AUTHORIZATION_ENVELOPE_KEYS | AUTH.COMMON_BINDING_KEYS
        )
        readme = (ROOT / "config" / "phase6-authorizations" / "README.md").read_text()
        self.assertIn("contains no operation authorization", readme)
        controller = (ROOT / "scripts" / "phase6" / "management-node-resize.py").read_text()
        phase2 = (ROOT / "scripts" / "infra" / "phase2.ps1").read_text()
        self.assertNotIn("verify-github-authorization.py", controller + phase2)
        self.assertNotIn("phase6-resize-apply", phase2)


if __name__ == "__main__":
    unittest.main()
