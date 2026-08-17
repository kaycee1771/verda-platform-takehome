#!/usr/bin/env python3
"""Materialize checksummed Kubernetes and CRD schemas for offline Kubeconform."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "schemas" / "schema-sources.lock.yaml"
CACHE = ROOT / ".local" / "schema-cache"
SOURCE_CACHE = CACHE / ".sources"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_DOWNLOAD_ATTEMPTS = 6


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def cached_payload(path: Path, expected_sha256: str) -> bytes | None:
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if sha256(payload) == expected_sha256:
        return payload
    return None


def retry_delay(error: HTTPError | URLError, attempt: int) -> int:
    if isinstance(error, HTTPError):
        retry_after = error.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(max(int(retry_after), 1), 30)
    return min(2**attempt, 30)


def download(url: str, expected_sha256: str) -> bytes:
    request = Request(url, headers={"User-Agent": "verda-platform-quality-bootstrap/1"})
    payload: bytes | None = None
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - locked HTTPS only
                payload = response.read()
            break
        except HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS or attempt == MAX_DOWNLOAD_ATTEMPTS:
                raise
            delay = retry_delay(error, attempt)
            print(f"[RETRY] locked schema download returned HTTP {error.code}; retrying in {delay}s")
            time.sleep(delay)
        except URLError as error:
            if attempt == MAX_DOWNLOAD_ATTEMPTS:
                raise
            delay = retry_delay(error, attempt)
            print(f"[RETRY] locked schema download failed transiently; retrying in {delay}s")
            time.sleep(delay)
    if payload is None:
        raise RuntimeError(f"locked schema download exhausted without a payload: {url}")
    actual = sha256(payload)
    if actual != expected_sha256:
        raise RuntimeError(f"checksum mismatch for {url}: expected {expected_sha256}, got {actual}")
    return payload


def main() -> int:
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    CACHE.mkdir(parents=True, exist_ok=True)
    SOURCE_CACHE.mkdir(parents=True, exist_ok=True)
    kubernetes = lock["kubernetes"]
    base = (
        "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
        f"{kubernetes['commit']}/v{kubernetes['version']}-standalone-strict"
    )
    for item in kubernetes["files"]:
        output = CACHE / item["name"]
        if cached_payload(output, item["sha256"]) is not None:
            print(f"[SCHEMA] core/{item['name']} checksum=verified cache=hit")
            continue
        payload = download(f"{base}/{item['name']}", item["sha256"])
        output.write_bytes(payload)
        print(f"[SCHEMA] core/{item['name']} checksum=verified cache=miss")

    for item in lock["crds"]["materialized"]:
        output = CACHE / item["output"]
        if cached_payload(output, item["output_sha256"]) is not None:
            print(
                f"[SCHEMA] crd/{item['output']} materialized-checksum=verified "
                "cache=hit"
            )
            continue
        source_cache = SOURCE_CACHE / f"{item['source_sha256']}.yaml"
        payload = cached_payload(source_cache, item["source_sha256"])
        if payload is None:
            payload = download(item["source"], item["source_sha256"])
            source_cache.write_bytes(payload)
            cache_state = "miss"
        else:
            cache_state = "hit"
        parse_payload = payload
        if item.get("normalization") == "longhorn-helm-labels-v1":
            marker = b'  labels: {{- include "longhorn.labels" . | nindent 4 }}\n'
            replacements = parse_payload.count(marker)
            if replacements < 1:
                raise RuntimeError("locked Longhorn normalization marker is absent")
            parse_payload = parse_payload.replace(marker, b"  labels:\n")
        documents = list(yaml.safe_load_all(parse_payload))
        selected = None
        for document in documents:
            if not isinstance(document, dict) or document.get("kind") != "CustomResourceDefinition":
                continue
            spec = document.get("spec", {})
            names = spec.get("names", {})
            if spec.get("group") != item["group"] or names.get("kind") != item["kind"]:
                continue
            for version in spec.get("versions", []):
                if version.get("name") == item["version"]:
                    selected = version.get("schema", {}).get("openAPIV3Schema")
                    break
        if selected is None:
            raise RuntimeError(f"locked CRD schema not found for {item['name']}")
        materialized = (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode()
        actual_output_sha256 = sha256(materialized)
        if actual_output_sha256 != item["output_sha256"]:
            raise RuntimeError(
                f"materialized checksum mismatch for {item['output']}: "
                f"expected {item['output_sha256']}, got {actual_output_sha256}"
            )
        output.write_bytes(materialized)
        print(
            f"[SCHEMA] crd/{item['output']} source-checksum=verified "
            f"source-cache={cache_state}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
