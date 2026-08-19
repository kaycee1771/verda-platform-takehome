#!/usr/bin/env python3
"""Fail-closed validation for the ignored Phase 4 support archive."""

from __future__ import annotations

import argparse
import gzip
import os
import pathlib
import re
import sys
from collections.abc import Mapping


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_TAR_STREAM_BYTES = 64 * 1024 * 1024
TAR_BLOCK_BYTES = 512
ROOT_MEMBER = "verda-rke2-support"
EXPECTED_CAPTURE_FILES = frozenset(
    {
        "api-ready.txt",
        "audit-metadata.txt",
        "certificates.txt",
        "cilium-status.txt",
        "disk.txt",
        "etcd-alarms.txt",
        "etcd-endpoints.txt",
        "etcd-health.txt",
        "etcd-members.txt",
        "firewall.txt",
        "links.txt",
        "memory.txt",
        "nodes.txt",
        "recent-journal.txt",
        "routes.txt",
        "secrets-encryption.txt",
        "service-status.txt",
        "snapshots.txt",
        "system-pods.txt",
    }
)
EXPECTED_MEMBERS = frozenset(
    {ROOT_MEMBER, *(f"{ROOT_MEMBER}/{name}" for name in EXPECTED_CAPTURE_FILES)}
)
MAX_MEMBERS = len(EXPECTED_MEMBERS)
FORBIDDEN_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | (re.MULTILINE if multiline else 0))
    for pattern, multiline in (
        (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", False),
        (r"\bhttps?://", False),
        (r"\bs3://", False),
        (r"\b(?:[a-z0-9-]+\.)+verda\.storage\b", False),
        (r"\bverda-takehome-mgmt-etcd-[a-z0-9-]+\b", False),
        (r"\b[a-z0-9.-]+\.sslip\.io\b", False),
        (r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", False),
        (r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", False),
        (r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", False),
        (r"(^|[^0-9a-f])[0-9a-f]{16}([^0-9a-f]|$)", False),
        (
            r"\b(token|secret|password|authorization|client-key-data|"
            r"access[_-]?key|credential)\b\s*[:=]",
            True,
        ),
    )
)
PROTECTED_ENVIRONMENT_NAMES = (
    "PHASE4_RKE2_TOKEN",
    "PHASE4_S3_ENDPOINT",
    "PHASE4_S3_BUCKET",
    "PHASE4_S3_ACCESS_KEY",
    "PHASE4_S3_SECRET_KEY",
    "PHASE4_S3_SESSION_TOKEN",
    "VERDA_CLIENT_ID",
    "VERDA_CLIENT_SECRET",
)


class SupportBundleError(RuntimeError):
    """Raised with a non-sensitive reason when an archive is rejected."""


def read_bounded_gzip(archive: pathlib.Path) -> bytes:
    """Fully consume one bounded gzip stream so trailing data cannot bypass policy."""

    expanded = bytearray()
    with archive.open("rb") as compressed_stream, gzip.GzipFile(
        fileobj=compressed_stream, mode="rb"
    ) as decompressed_stream:
        while True:
            remaining = MAX_TAR_STREAM_BYTES - len(expanded)
            payload = decompressed_stream.read(min(64 * 1024, remaining + 1))
            if not payload:
                break
            expanded.extend(payload)
            if len(expanded) > MAX_TAR_STREAM_BYTES:
                raise SupportBundleError("decompressed tar stream exceeds the bound")
    return bytes(expanded)


def remove_unvalidated_archive(archive: pathlib.Path) -> None:
    """Remove an unvalidated archive and prove that no local residue remains."""

    try:
        archive.unlink(missing_ok=True)
    except OSError as exc:
        raise SupportBundleError("unvalidated archive cleanup failed") from exc
    if archive.exists():
        raise SupportBundleError("unvalidated archive cleanup failed")


def _canonical_text(field: bytes) -> str:
    if b"\0" in field:
        value, padding = field.split(b"\0", 1)
        if any(padding):
            raise SupportBundleError("archive text metadata has nonzero padding")
    else:
        value = field
    try:
        return value.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise SupportBundleError("archive text metadata is not canonical ASCII") from exc


def _canonical_octal(field: bytes, *, allow_empty: bool = False) -> int:
    value = field.rstrip(b"\0 ")
    if not value:
        if allow_empty:
            return 0
        raise SupportBundleError("archive numeric metadata is empty")
    if any(character not in b"01234567" for character in value):
        raise SupportBundleError("archive numeric metadata is not canonical octal")
    return int(value, 8)


def read_canonical_tar_payloads(tar_payload: bytes) -> list[str]:
    """Parse only the exact basic tar shape, before any extension can be hidden."""

    payloads: list[str] = []
    seen: set[str] = set()
    expanded_bytes = 0
    offset = 0
    while True:
        if offset + TAR_BLOCK_BYTES > len(tar_payload):
            raise SupportBundleError("archive has no canonical terminal blocks")
        header = tar_payload[offset : offset + TAR_BLOCK_BYTES]
        if not any(header):
            terminal = tar_payload[offset:]
            if len(terminal) < 2 * TAR_BLOCK_BYTES or any(terminal):
                raise SupportBundleError("archive has noncanonical trailing tar data")
            break
        if len(seen) >= MAX_MEMBERS:
            raise SupportBundleError("archive member count exceeds the bound")

        recorded_checksum = _canonical_octal(header[148:156])
        checksum_header = bytearray(header)
        checksum_header[148:156] = b" " * 8
        if sum(checksum_header) != recorded_checksum:
            raise SupportBundleError("archive header checksum is invalid")
        if header[345:500] != b"\0" * 155 or header[157:257] != b"\0" * 100:
            raise SupportBundleError("archive contains unsupported name or link metadata")
        if (header[257:263], header[263:265]) not in {
            (b"ustar ", b" \0"),
            (b"ustar\0", b"00"),
        }:
            raise SupportBundleError("archive format is not canonical basic tar")

        name = _canonical_text(header[0:100])
        member_type = header[156:157]
        mode = _canonical_octal(header[100:108])
        uid = _canonical_octal(header[108:116], allow_empty=True)
        gid = _canonical_octal(header[116:124], allow_empty=True)
        size = _canonical_octal(header[124:136])
        _canonical_octal(header[136:148])
        uname = _canonical_text(header[265:297])
        gname = _canonical_text(header[297:329])
        devmajor = _canonical_octal(header[329:337], allow_empty=True)
        devminor = _canonical_octal(header[337:345], allow_empty=True)
        normalized_name = ROOT_MEMBER if name == f"{ROOT_MEMBER}/" else name

        if normalized_name not in EXPECTED_MEMBERS:
            raise SupportBundleError("archive path is outside the allowlist")
        if normalized_name in seen:
            raise SupportBundleError("archive contains a duplicate member")
        if uid != 0 or gid != 0 or devmajor != 0 or devminor != 0:
            raise SupportBundleError("archive ownership metadata is unexpected")
        if uname not in {"", "root"} or gname not in {"", "root"}:
            raise SupportBundleError("archive identity metadata is unexpected")

        data_start = offset + TAR_BLOCK_BYTES
        data_end = data_start + size
        padded_size = (size + TAR_BLOCK_BYTES - 1) // TAR_BLOCK_BYTES * TAR_BLOCK_BYTES
        next_offset = data_start + padded_size
        if data_end > len(tar_payload) or next_offset > len(tar_payload):
            raise SupportBundleError("archive member exceeds the tar stream")
        if any(tar_payload[data_end:next_offset]):
            raise SupportBundleError("archive member has nonzero data padding")

        if normalized_name == ROOT_MEMBER:
            if member_type != b"5" or mode != 0o700 or size != 0:
                raise SupportBundleError("archive root metadata is not canonical")
        else:
            if member_type not in {b"0", b"\0"} or mode != 0o600:
                raise SupportBundleError("archive capture metadata is not canonical")
            if size > MAX_EXPANDED_BYTES:
                raise SupportBundleError("archive member exceeds the expansion bound")
            expanded_bytes += size
            if expanded_bytes > MAX_EXPANDED_BYTES:
                raise SupportBundleError("archive exceeds the total expansion bound")
            try:
                payloads.append(
                    tar_payload[data_start:data_end].decode("utf-8", errors="strict")
                )
            except UnicodeDecodeError as exc:
                raise SupportBundleError("archive member is not UTF-8 text") from exc

        seen.add(normalized_name)
        offset = next_offset

    if seen != EXPECTED_MEMBERS:
        raise SupportBundleError("archive capture set is incomplete")
    return payloads


def validate_archive(
    archive: pathlib.Path, environment: Mapping[str, str] | None = None
) -> None:
    """Validate and retain a clean archive; delete it on every rejection."""

    process_environment = os.environ if environment is None else environment
    try:
        size = archive.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise SupportBundleError("archive size is outside the bounded contract")

        payloads = read_canonical_tar_payloads(read_bounded_gzip(archive))

        content = "\n".join(payloads)
        if any(pattern.search(content) for pattern in FORBIDDEN_PATTERNS):
            raise SupportBundleError("archive failed the forbidden-pattern scan")
        for name in PROTECTED_ENVIRONMENT_NAMES:
            value = process_environment.get(name, "")
            if value and value in content:
                raise SupportBundleError("archive contains protected process-only material")
    except (OSError, EOFError, gzip.BadGzipFile, SupportBundleError) as exc:
        remove_unvalidated_archive(archive)
        if isinstance(exc, SupportBundleError):
            raise
        raise SupportBundleError("archive could not be safely inspected") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--remove-unvalidated", action="store_true")
    args = parser.parse_args()
    try:
        if args.remove_unvalidated:
            remove_unvalidated_archive(args.archive)
        else:
            validate_archive(args.archive)
    except SupportBundleError:
        print("[FAIL] Support-bundle safety operation failed closed.", file=sys.stderr)
        return 1
    if args.remove_unvalidated:
        print("[PASS] Unvalidated support-bundle residue is absent.")
    else:
        print("[PASS] Support-bundle archive bounds, paths, content, and protected-value checks are clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
