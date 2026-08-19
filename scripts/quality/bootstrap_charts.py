#!/usr/bin/env python3
"""Materialize exact Phase 5 Helm archives into the ignored offline cache."""

from __future__ import annotations

import hashlib
import os
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "versions.lock.yaml"
CACHE = ROOT / ".local" / "chart-cache"
PHASE5_CHARTS = {
    "argocd": "argo-cd",
    "cert_manager": "cert-manager",
    "longhorn": "longhorn",
}
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_CHART_YAML_BYTES = 64 * 1024


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download(url: str, expected_sha256: str) -> bytes:
    if not url.startswith("https://"):
        raise RuntimeError("chart archive URL must use HTTPS")
    for attempt in range(1, 4):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "verda-phase5-chart-lock/1"}),
                timeout=45,
            ) as response:
                payload = response.read(MAX_ARCHIVE_BYTES + 1)
            if len(payload) > MAX_ARCHIVE_BYTES:
                raise RuntimeError("chart archive exceeds the bounded size")
            if sha256(payload) != expected_sha256:
                raise RuntimeError("chart archive checksum mismatch")
            return payload
        except (HTTPError, URLError) as error:
            if attempt == 3:
                raise RuntimeError("chart archive download failed after bounded retries") from error
            time.sleep(attempt)
    raise AssertionError("unreachable")


def validate_chart(payload_path: Path, chart_name: str, version: str, app_version: str) -> None:
    try:
        with tarfile.open(payload_path, mode="r:gz") as archive:
            expected_name = f"{chart_name}/Chart.yaml"
            members = [member for member in archive if member.name == expected_name]
            if len(members) != 1 or not members[0].isfile():
                raise RuntimeError("chart archive has no unique regular Chart.yaml")
            if members[0].size > MAX_CHART_YAML_BYTES:
                raise RuntimeError("chart metadata exceeds the bounded size")
            stream = archive.extractfile(members[0])
            if stream is None:
                raise RuntimeError("chart metadata is unreadable")
            metadata = yaml.safe_load(stream.read(MAX_CHART_YAML_BYTES + 1))
    except (tarfile.TarError, OSError, yaml.YAMLError) as error:
        raise RuntimeError("chart archive validation failed") from error
    if not isinstance(metadata, dict):
        raise RuntimeError("chart metadata must be a mapping")
    if (
        metadata.get("name") != chart_name
        or str(metadata.get("version")) != version
        or str(metadata.get("appVersion")) != app_version
    ):
        raise RuntimeError("chart metadata does not match the version lock")


def main() -> int:
    document = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    charts = document.get("helm_charts", {})
    CACHE.mkdir(parents=True, exist_ok=True)
    for lock_name, chart_name in PHASE5_CHARTS.items():
        item = charts.get(lock_name)
        if not isinstance(item, dict):
            raise RuntimeError(f"missing chart lock: {lock_name}")
        version = str(item.get("version", ""))
        app_version = str(item.get("app_version", ""))
        expected_sha256 = str(item.get("archive_sha256", ""))
        url = str(item.get("archive_url", ""))
        if len(expected_sha256) != 64 or not version or not app_version:
            raise RuntimeError(f"incomplete chart lock: {lock_name}")
        filename = url.rsplit("/", 1)[-1]
        destination = CACHE / filename
        cache_state = "hit"
        if not destination.is_file() or sha256(destination.read_bytes()) != expected_sha256:
            payload = download(url, expected_sha256)
            with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as temporary:
                temporary.write(payload)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
            cache_state = "miss"
        validate_chart(destination, chart_name, version, app_version)
        print(
            f"[CHART] {lock_name} version={version} checksum=verified "
            f"metadata=verified cache={cache_state}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
