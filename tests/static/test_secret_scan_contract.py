#!/usr/bin/env python3
"""Static fail-closed checks for the repository secret-scan boundary."""

from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[2]


class SecretScanContractTests(unittest.TestCase):
    def test_working_tree_scan_uses_the_git_controlled_surface(self) -> None:
        script = (ROOT / "scripts/quality/secret-scan.sh").read_text()

        self.assertIn(
            "git -C \"${repo_root}\" ls-files -z --cached --others --exclude-standard",
            script,
        )
        self.assertIn('scan_temp="$(mktemp -d -t verda-gitleaks.XXXXXX)"', script)
        self.assertIn('trap cleanup EXIT', script)
        self.assertIn('"${scan_root}"', script)
        self.assertIn('ls-files --deleted --error-unmatch -- "${path}"', script)
        self.assertIn("prior content remains covered by the complete-history scan", script)
        self.assertNotIn("--exclude-path .local", script)

    def test_complete_history_scan_remains_enabled_and_redacted(self) -> None:
        script = (ROOT / "scripts/quality/secret-scan.sh").read_text()

        self.assertIn("gitleaks git", script)
        self.assertIn("--log-opts='--all'", script)
        self.assertGreaterEqual(script.count("--redact=100"), 2)


if __name__ == "__main__":
    unittest.main()
