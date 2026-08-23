import hashlib
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "quality" / "bootstrap_charts.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_charts", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def chart_archive(name: str, version: str, app_version: str) -> bytes:
    output = io.BytesIO()
    payload = yaml.safe_dump(
        {"apiVersion": "v2", "name": name, "version": version, "appVersion": app_version}
    ).encode()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"{name}/Chart.yaml")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


class BootstrapChartTests(unittest.TestCase):
    def test_all_pinned_locks_have_exact_https_archives_and_checksums(self):
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
        self.assertEqual(len(RUNTIME.PHASE5_CHARTS), 3)
        self.assertEqual(len(RUNTIME.PHASE6_CHARTS), 8)
        self.assertEqual(set(RUNTIME.PINNED_CHARTS), set(RUNTIME.PHASE5_CHARTS) | set(RUNTIME.PHASE6_CHARTS))
        for name, chart_name in RUNTIME.PINNED_CHARTS.items():
            with self.subTest(chart=name):
                item = lock["helm_charts"][name]
                self.assertTrue(item["archive_url"].startswith("https://"))
                self.assertRegex(item["archive_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(
                    item.get("archive_digest_source", item["source"]).startswith("https://")
                )
                self.assertTrue(item["archive_url"].endswith(f"/{chart_name}-{item['version']}.tgz"))
                self.assertTrue(item["version"])
                self.assertTrue(item["app_version"])

    def test_phase_six_selection_metadata_is_explicitly_pending_runtime_admission(self):
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
        for name in RUNTIME.PHASE6_CHARTS:
            with self.subTest(chart=name):
                item = lock["helm_charts"][name]
                self.assertIn("kube_version_constraint", item)
                self.assertTrue(item["compatibility_source"].startswith("https://"))
                self.assertEqual(
                    item["selection_status"],
                    "phase-6-provenance-verified-capacity-and-live-compatibility-pending",
                )

    def test_metadata_must_match_the_locked_chart(self):
        payload = chart_archive("argo-cd", "10.3.3", "v3.5.1")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.tgz"
            path.write_bytes(payload)
            RUNTIME.validate_chart(path, "argo-cd", "10.3.3", "v3.5.1")
            with self.assertRaisesRegex(RuntimeError, "metadata"):
                RUNTIME.validate_chart(path, "argo-cd", "10.3.4", "v3.5.1")

    def test_download_is_bounded_and_checksum_verified(self):
        payload = chart_archive("longhorn", "1.12.1", "v1.12.1")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return payload

        with mock.patch.object(RUNTIME, "urlopen", return_value=Response()):
            self.assertEqual(
                RUNTIME.download("https://example.invalid/chart.tgz", hashlib.sha256(payload).hexdigest()),
                payload,
            )
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                RUNTIME.download("https://example.invalid/chart.tgz", "0" * 64)

    def test_cached_archive_must_be_bounded_regular_and_checksum_exact(self):
        payload = chart_archive("rancher", "2.14.3", "v2.14.3")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "rancher-2.14.3.tgz"
            archive.write_bytes(payload)
            self.assertEqual(RUNTIME.cached_sha256(archive), hashlib.sha256(payload).hexdigest())
            archive.write_bytes(b"not the chart")
            self.assertNotEqual(RUNTIME.cached_sha256(archive), hashlib.sha256(payload).hexdigest())
            link = root / "linked.tgz"
            try:
                link.symlink_to(archive)
            except OSError:
                return
            self.assertIsNone(RUNTIME.cached_sha256(link))


if __name__ == "__main__":
    unittest.main()
