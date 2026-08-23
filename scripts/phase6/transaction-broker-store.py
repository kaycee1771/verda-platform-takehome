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
import re
import secrets
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
AUTHORIZATION_KEYS = {
    "schema_version", "phase", "status", "authorization_mode", "repository", "workflow_id", "pr_number",
    "source_parent_commit", "source_tree_oid", "source_tree_manifest_sha256", "operation_id", "operation_nonce",
    "node", "direction", "plan_sha256", "plan_semantic_sha256", "state_lineage_sha256", "state_serial",
    "contract_sha256", "tool_lock_sha256", "broker_sha256", "transaction_policy_sha256",
    "rollback_policy_sha256", "journal_sha256", "journal_generation", "journal_state", "user_approval_sha256",
    "security_review_sha256", "reliability_review_sha256", "security_approved", "reliability_approved",
    "preflight_sha256", "cost_sha256", "capacity_sha256", "collector_sha256", "etcd_backup_sha256",
    "data_backup_sha256", "provider_facts_sha256", "approved_resource_expiry_utc", "approved_cost_ceiling_usd",
    "issued_at", "start_by", "complete_by", "minimum_recovery_margin_seconds", "raw_values_recorded",
}
AUTHORIZATION_SCHEMA_SHA256 = "1b87f889a9bfa3c638f7c637918ee817254beb81c2ca47005d80b9bf044da442"
VERIFIER_RECEIPT_KEYS = {"schema_version", "status", "phase", "authorization_mode", "operation_id",
                         "authorization_commit", "authorization_sha256", "authorization_history_sha256",
                         "source_parent_commit", "workflow_id", "pr_number", "complete_by",
                         "web_flow_fingerprint", "requires_reverification_before_use", "raw_values_recorded"}


class StoreRefused(ValueError):
    pass


class SynchronousAuthorizationVerifier:
    """Explicit adapter interface; production implementations invoke the real verifier synchronously."""
    def verify(self, authorization_path: pathlib.Path, raw: bytes,
               parsed: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class CallableAuthorizationVerifier(SynchronousAuthorizationVerifier):
    def __init__(self, function: Callable[[pathlib.Path, bytes, dict[str, Any]], dict[str, Any]]) -> None:
        self.function = function

    def verify(self, authorization_path: pathlib.Path, raw: bytes,
               parsed: dict[str, Any]) -> dict[str, Any]:
        return self.function(authorization_path, raw, parsed)


class CheckedInAuthorizationVerifier(SynchronousAuthorizationVerifier):
    """Concrete adapter to the repository's synchronous protected-main verifier."""
    def __init__(self, repository: Any, github: Any) -> None:
        spec = importlib.util.spec_from_file_location("phase6_github_authorization_verifier",
                                                      HERE / "verify-github-authorization.py")
        if not spec or not spec.loader:
            refuse("checked-in authorization verifier is unavailable")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.function, self.repository, self.github = module.verify_authorization, repository, github

    def verify(self, authorization_path: pathlib.Path, raw: bytes,
               parsed: dict[str, Any]) -> dict[str, Any]:
        receipt = self.function(repository=self.repository, github=self.github,
                                operation_id=parsed["operation_id"], binding=parsed)
        if receipt.get("authorization_sha256") != digest_bytes(raw):
            refuse("checked-in verifier did not verify the exact held authorization bytes")
        return receipt


def refuse(message: str) -> None:
    raise StoreRefused(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            refuse("durable write made no forward progress")
        view = view[written:]


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
    owner_only = not bool(status.st_mode & (stat.S_IRWXG | stat.S_IRWXO))
    if os.name == "nt":
        owner_only = _windows_owner_protected_dacl(path)
    return {"reparse": stat.S_ISLNK(status.st_mode) or bool(getattr(status, "st_file_attributes", 0) & 0x400),
            "nlink": status.st_nlink, "device": status.st_dev, "identity": status.st_ino,
            "owner_only": owner_only}


def _windows_owner_protected_dacl(path: pathlib.Path, *, require_current_owner: bool = True,
                                  require_protected: bool = True) -> bool:
    """Require current-user ownership, protected DACL, and no broad write ACE."""
    import ctypes
    from ctypes import wintypes
    advapi, kernel32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    advapi.GetNamedSecurityInfoW.argtypes = (wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p))
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = (); kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p); advapi.EqualSid.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,); kernel32.CloseHandle.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int)
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    advapi.GetAce.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,); kernel32.LocalFree.restype = ctypes.c_void_p
    if advapi.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                    ctypes.byref(dacl), None, ctypes.byref(descriptor)) != 0:
        return False
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        advapi.GetSecurityDescriptorControl.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                                                        ctypes.POINTER(wintypes.DWORD))
        if not advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)) \
                or (require_protected and not control.value & 0x1000) or not dacl.value:
            return False
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token)):
            return False
        try:
            needed = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)):
                return False
            current_sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            if require_current_owner and not advapi.EqualSid(owner, current_sid):
                return False
            current_text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(current_sid, ctypes.byref(current_text)): return False
            try: current_text_value = current_text.value
            finally: kernel32.LocalFree(current_text)
        finally:
            kernel32.CloseHandle(token)
        class ACL_SIZE_INFORMATION(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD),
                        ("AclBytesFree", wintypes.DWORD)]
        info = ACL_SIZE_INFORMATION()
        if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            return False
        owner_text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(owner_text)): return False
        try:
            if not require_current_owner and owner_text.value not in {
                    current_text_value, "S-1-5-18", "S-1-5-32-544",
                    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}:
                return False
            allowed_writers = {owner_text.value, current_text_value, "S-1-3-4", "S-1-5-18", "S-1-5-32-544"}
        finally:
            kernel32.LocalFree(owner_text)
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)): return False
            raw = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte))
            # Only simple allow and deny ACEs are accepted. Object/callback ACEs
            # have semantics this boundary deliberately refuses to interpret.
            if raw[0] not in {0, 1, 5, 6}:
                if require_protected: return False
                continue
            if raw[0] in {1, 6}: continue
            if raw[1] & 0x8:  # INHERIT_ONLY_ACE does not grant access to this held ancestor.
                continue
            mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD))[0]
            sid_offset = 8
            if raw[0] == 5:
                object_flags = ctypes.cast(ace.value + 8, ctypes.POINTER(wintypes.DWORD))[0]
                sid_offset = 12 + (16 if object_flags & 0x1 else 0) + (16 if object_flags & 0x2 else 0)
            sid = ctypes.c_void_p(ace.value + sid_offset); text_sid = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text_sid)): return False
            try:
                write_mask = (0x40000000 | 0x10000000 | 0x00010000 | 0x00040000 | 0x00080000
                              | 0x0002 | 0x0004 | 0x0010 | 0x0040 | 0x0100)
                if text_sid.value not in allowed_writers and mask & write_mask:
                    root_create_only = (not require_protected and path == pathlib.Path(path.anchor)
                                        and text_sid.value == "S-1-5-11" and mask == 0x4 and raw[1] == 0)
                    if not root_create_only: return False
            finally:
                kernel32.LocalFree(text_sid)
        return True
    finally:
        kernel32.LocalFree(descriptor)


def _protect_windows_path(path: pathlib.Path) -> None:
    import ctypes
    from ctypes import wintypes
    advapi, kernel32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.SetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
    advapi.SetFileSecurityW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,); kernel32.LocalFree.restype = ctypes.c_void_p
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;GA;;;BA)", 1, ctypes.byref(descriptor), None):
        refuse("unable to construct protected filesystem DACL")
    try:
        if not advapi.SetFileSecurityW(str(path), 0x4, descriptor):
            refuse("unable to apply protected filesystem DACL")
    finally:
        kernel32.LocalFree(descriptor)


def _windows_mutex_handle_trusted(handle: Any) -> bool:
    """Validate owner/protection and native ACEs of an existing mutex."""
    import ctypes
    from ctypes import wintypes
    advapi, kernel32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor, owner, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    advapi.GetSecurityInfo.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p))
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                                                     ctypes.POINTER(wintypes.DWORD))
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int)
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    advapi.GetAce.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = (); kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi.GetTokenInformation.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,); kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,); kernel32.LocalFree.restype = ctypes.c_void_p
    if advapi.GetSecurityInfo(handle, 6, 0x1 | 0x4, ctypes.byref(owner), None,
                              ctypes.byref(dacl), None, ctypes.byref(descriptor)) != 0:
        return False
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if (not dacl.value or not advapi.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)) or not control.value & 0x1000):
            return False
        token, needed = wintypes.HANDLE(), wintypes.DWORD()
        if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token)): return False
        try:
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)): return False
            current_sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            current_text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(current_sid, ctypes.byref(current_text)): return False
            try: approved = {current_text.value, "S-1-5-18", "S-1-5-32-544"}
            finally: kernel32.LocalFree(current_text)
        finally: kernel32.CloseHandle(token)
        owner_text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(owner_text)): return False
        try:
            if owner_text.value not in approved: return False
        finally: kernel32.LocalFree(owner_text)
        class ACL_SIZE_INFORMATION(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD),
                        ("AclBytesFree", wintypes.DWORD)]
        info = ACL_SIZE_INFORMATION()
        if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2): return False
        write_mask = 0x40000000 | 0x10000000 | 0x1 | 0x00010000 | 0x00040000 | 0x00080000
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)): return False
            raw = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte)); ace_type = raw[0]
            if ace_type not in {0, 1}: return False
            if ace_type == 1: continue
            mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD))[0]
            sid_text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(ctypes.c_void_p(ace.value + 8), ctypes.byref(sid_text)): return False
            try:
                if sid_text.value not in approved | {"S-1-3-4"} and mask & write_mask: return False
            finally: kernel32.LocalFree(sid_text)
        return True
    finally:
        kernel32.LocalFree(descriptor)


class NamedMutex:
    """OS mutex in production; process lock fallback keeps tests deterministic."""

    def __init__(self, name: str, *, held_parent_fd: int | None = None) -> None:
        self.name = name
        self.handle: Any = None
        self.abandoned = False
        self.directory_handle: int | None = None
        self.held_parent_fd = held_parent_fd
        self.owns_parent = held_parent_fd is None

    def _accept_wait_result(self, result: int) -> None:
        if result == 0:
            return
        if result == 0x80:
            self.abandoned = True; return
        if result == 0x102:
            refuse("another writer holds the named broker/state mutex")
        refuse("named broker/state mutex wait failed")

    def __enter__(self) -> "NamedMutex":
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
                wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
            advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
            class SECURITY_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                            ("bInheritHandle", wintypes.BOOL)]
            descriptor = ctypes.c_void_p()
            # Protected DACL: owner rights, LocalSystem, and built-in Administrators only.
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    "D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;GA;;;BA)", 1, ctypes.byref(descriptor), None):
                refuse("unable to construct protected named-mutex security descriptor")
            security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
            self.kernel32 = kernel32
            ctypes.set_last_error(0)
            self.handle = kernel32.CreateMutexW(ctypes.byref(security), False, self.name)
            already_exists = ctypes.get_last_error() == 183
            kernel32.LocalFree(descriptor)
            if not self.handle:
                refuse("unable to create the named broker/state mutex")
            if already_exists:
                if not _windows_mutex_handle_trusted(self.handle):
                    kernel32.CloseHandle(self.handle); self.handle = None
                    refuse("untrusted pre-existing named mutex DACL/owner differs")
            result = kernel32.WaitForSingleObject(self.handle, 0)
            try:
                self._accept_wait_result(result)
            except StoreRefused:
                kernel32.CloseHandle(self.handle); self.handle = None
                raise
        else:
            import fcntl
            lock_root = pathlib.Path(tempfile.gettempdir()) / f"verda-phase6-locks-{os.getuid()}"
            lock_root.mkdir(mode=0o700, exist_ok=True)
            root_status = lock_root.lstat()
            if (stat.S_ISLNK(root_status.st_mode) or root_status.st_uid != os.getuid()
                    or stat.S_IMODE(root_status.st_mode) != 0o700):
                refuse("broker lock directory ownership/mode/identity differs")
            self.directory_handle = self.held_parent_fd
            if self.directory_handle is None:
                self.directory_handle = os.open(lock_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                                 | getattr(os, "O_NOFOLLOW", 0))
                try:
                    fcntl.flock(self.directory_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (OSError, BlockingIOError):
                    os.close(self.directory_handle); self.directory_handle = None
                    refuse("another writer holds the shared protected-state lock parent")
            filename = f"verda-{digest_bytes(self.name.encode())}.lockdir"
            try: os.mkdir(filename, 0o700, dir_fd=self.directory_handle)
            except FileExistsError: pass
            lock_path = lock_root / filename
            sentinel = lock_path / ".boundary"
            sentinel.touch(mode=0o600, exist_ok=True)
            descriptor = os.open(filename, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                 | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.directory_handle)
            status = os.fstat(descriptor)
            path_status = os.stat(filename, dir_fd=self.directory_handle, follow_symlinks=False)
            if (not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid()
                    or stat.S_IMODE(status.st_mode) != 0o700
                    or (status.st_dev, status.st_ino) != (path_status.st_dev, path_status.st_ino)):
                os.close(descriptor); refuse("broker mutex lock directory identity differs")
            self.handle = descriptor
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                os.close(self.handle); self.handle = None
                if self.owns_parent: os.close(self.directory_handle)
                self.directory_handle = None
                refuse("another writer holds the named broker/state mutex")
            path_status = os.stat(filename, dir_fd=self.directory_handle, follow_symlinks=False)
            held = os.fstat(self.handle)
            if (held.st_dev, held.st_ino) != (path_status.st_dev, path_status.st_ino):
                os.close(self.handle); self.handle = None
                os.close(self.directory_handle); self.directory_handle = None
                refuse("broker mutex lock path was replaced after flock")
        return self

    def __exit__(self, *_: Any) -> None:
        if os.name == "nt":
            self.kernel32.ReleaseMutex(self.handle)
            self.kernel32.CloseHandle(self.handle)
        elif self.handle:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            os.close(self.handle)
            if self.directory_handle is not None:
                if self.owns_parent:
                    fcntl.flock(self.directory_handle, fcntl.LOCK_UN)
                    os.close(self.directory_handle)
                self.directory_handle = None


class PosixLockParent:
    """One stable parent-inode fence shared by a composite broker lease."""
    def __enter__(self) -> int:
        import fcntl
        root = pathlib.Path(tempfile.gettempdir()) / f"verda-phase6-locks-{os.getuid()}"
        root.mkdir(mode=0o700, exist_ok=True)
        status = root.lstat()
        if stat.S_ISLNK(status.st_mode) or status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) != 0o700:
            refuse("shared lock parent ownership/mode differs")
        self.fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try: fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            os.close(self.fd); refuse("another writer holds the shared protected-state lock parent")
        held, current = os.fstat(self.fd), root.lstat()
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            os.close(self.fd); refuse("shared lock parent identity changed")
        return self.fd

    def __exit__(self, *_: Any) -> None:
        import fcntl
        fcntl.flock(self.fd, fcntl.LOCK_UN); os.close(self.fd)


class DurableBrokerStore:
    def __init__(self, *, operation_id: str, base: pathlib.Path | None = None,
                 clock: Callable[[], dt.datetime], security_probe: Callable[[pathlib.Path], dict[str, Any]] = default_security_probe,
                 verifier: SynchronousAuthorizationVerifier |
                 Callable[[pathlib.Path, bytes, dict[str, Any]], dict[str, Any]] | None = None,
                 allow_test_verifier: bool = False,
                 allow_test_security_probe: bool = False,
                 state_path: pathlib.Path | None = None,
                 crash_hook: Callable[[str], None] = lambda _stage: None) -> None:
        if os.name != "nt":
            refuse("protected Phase 6 broker store is Windows-only")
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
        self.clock, self.security_probe = clock, security_probe
        self.custom_security_probe = security_probe is not default_security_probe
        if self.custom_security_probe and not allow_test_security_probe:
            refuse("custom security probe is test-only")
        self.verifier = CallableAuthorizationVerifier(verifier) if callable(verifier) else verifier
        self.allow_test_verifier = allow_test_verifier
        if isinstance(self.verifier, CallableAuthorizationVerifier) and not allow_test_verifier:
            refuse("callable authorization verifier is test-only")
        self.crash_hook = crash_hook
        self.operation_mutex = f"Local\\VerdaPhase6Broker-{operation_id}"
        expected_state = pathlib.Path(os.environ.get("VERDA_TF_STATE_PATH",
                                                      str(canonical_base / "terraform" / "management.tfstate")))
        selected_state = state_path or expected_state
        if not selected_state.is_absolute() or selected_state.resolve(strict=False) != expected_state.resolve(strict=False):
            refuse("broker state path is not the exact canonical Phase 2 state path")
        self.state_path = selected_state.resolve(strict=False)
        canonical_state = str(self.state_path).lower()
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
                within_base = cursor == self.base or self.base in cursor.parents
                if within_base:
                    if not facts.get("owner_only", False):
                        refuse("broker path ACL is not owner-only")
                elif os.name == "nt" and not (self.custom_security_probe and facts.get("owner_only", False)) \
                        and not _windows_owner_protected_dacl(
                        cursor, require_current_owner=False, require_protected=False):
                    refuse("broker system ancestor permits an untrusted writer")
                if regular and cursor == absolute and facts.get("nlink") != 1:
                    refuse("broker protected file has aliases/hardlinks")
            cursor = cursor.parent
        return self.security_probe(absolute) if absolute.exists() else {}

    def initialize(self) -> None:
        if os.name != "nt":
            refuse("protected Phase 6 broker store is Windows-only")
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        if os.name == "nt":
            _protect_windows_path(self.base); _protect_windows_path(self.root)
        self._secure(self.base)
        self._secure(self.root)
        if self.root.resolve(strict=True) != (self.base.resolve(strict=True) / "phase6-resize-control"):
            refuse("control root is not canonical Base\\phase6-resize-control")

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        if os.name != "nt":
            refuse("protected Phase 6 broker store is Windows-only")
        with NamedMutex(self.operation_mutex) as operation_lock, NamedMutex(self.state_mutex) as state_lock:
            self.last_lock_abandoned = operation_lock.abandoned or state_lock.abandoned
            yield

    def _recover_stale_snapshots(self) -> None:
        temp_grammar = re.compile(r"(\.phase6-(intent|snapshot)-[0-9a-f]{32}\.tmp)(\.deleting)?")
        for candidate in self.root.iterdir():
            if candidate.name.startswith(".phase6-"):
                if not temp_grammar.fullmatch(candidate.name): refuse("ambiguous snapshot temporary file")
                self._secure(candidate, regular=True)
                match = temp_grammar.fullmatch(candidate.name)
                if not match: refuse("ambiguous snapshot temporary file")
                self._delete_windows_write_through(candidate, original_name=match.group(1))
        grammar = re.compile(r"(state-([0-9a-f]{64})-([0-9a-f]{32})\.read-only\.tfstate)(\.deleting)?")
        entries = {item.name: item for item in self.root.iterdir() if item.name.startswith("state-")}
        for name, path in list(entries.items()):
            if name.endswith(".manifest.json.deleting"):
                original_marker = name.removesuffix(".deleting")
                if not grammar.fullmatch(original_marker.removesuffix(".manifest.json")):
                    refuse("ambiguous snapshot manifest tombstone")
                manifest = self._read_json(path)
                if manifest.get("operation_id") != self.operation_id or manifest.get("state") != "PLANNED":
                    refuse("snapshot manifest tombstone differs")
                self._delete_windows_write_through(path, original_name=original_marker)
                entries.pop(name)
        manifests = {name: path for name, path in entries.items() if name.endswith(".manifest.json")}
        snapshots = {name: path for name, path in entries.items() if not name.endswith(".manifest.json")}
        for name, candidate in list(snapshots.items()):
            match = grammar.fullmatch(name)
            if not match: refuse("ambiguous stale Terraform snapshot filename")
            original = match.group(1); marker_name = original + ".manifest.json"
            marker = manifests.pop(marker_name, None)
            if marker is None: refuse("stale Terraform snapshot lacks exact manifest")
            manifest = self._read_json(marker)
            if (set(manifest) != {"schema_version", "operation_id", "snapshot_name", "snapshot_sha256", "state",
                                  "created_at", "raw_values_recorded"}
                    or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["operation_id"] != self.operation_id
                    or manifest["snapshot_name"] != original or manifest["snapshot_sha256"] != match.group(2)
                    or manifest["state"] != "PLANNED"
                    or manifest["raw_values_recorded"] is not False):
                refuse("stale Terraform snapshot manifest differs")
            candidate_raw = self._stable_bytes(candidate)
            if digest_bytes(candidate_raw) != manifest["snapshot_sha256"]:
                if candidate_raw:
                    refuse("stale Terraform snapshot digest differs from manifest")
                self._delete_windows_write_through(candidate, original_name=original)
                self._delete_windows_write_through(marker, original_name=marker_name)
                continue
            self._delete_windows_write_through(candidate, original_name=original)
            self._delete_windows_write_through(marker, original_name=marker_name)
        for marker_name, marker in manifests.items():
            original = marker_name.removesuffix(".manifest.json")
            if not grammar.fullmatch(original): refuse("orphan Terraform snapshot manifest differs")
            marker_raw = self._stable_bytes(marker)
            if not marker_raw:
                self._delete_windows_write_through(marker, original_name=marker_name)
                continue
            manifest = self._read_json(marker)
            if (manifest.get("schema_version") != 1 or manifest.get("operation_id") != self.operation_id
                    or manifest.get("snapshot_name") != original or manifest.get("state") != "PLANNED"):
                refuse("orphan Terraform snapshot intent differs")
            self._delete_windows_write_through(marker, original_name=marker_name)

    def _delete_windows_write_through(self, path: pathlib.Path, *, original_name: str) -> None:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel32.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,); kernel32.CloseHandle.restype = wintypes.BOOL
        class FILE_INFO(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("creation_low", wintypes.DWORD),
                        ("creation_high", wintypes.DWORD), ("access_low", wintypes.DWORD),
                        ("access_high", wintypes.DWORD), ("write_low", wintypes.DWORD),
                        ("write_high", wintypes.DWORD), ("volume", wintypes.DWORD),
                        ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                        ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
        handle = kernel32.CreateFileW(str(path), 0x80000000 | 0x00010000, 0x1 | 0x2, None, 3, 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value: refuse("unable to hold exact snapshot object for deletion")
        kind = "manifest" if ".manifest.json" in original_name else "snapshot"
        try:
            before = FILE_INFO(); length = kernel32.GetFinalPathNameByHandleW(handle, None, 0, 0)
            final = ctypes.create_unicode_buffer(length + 1)
            if (not kernel32.GetFileInformationByHandle(handle, ctypes.byref(before)) or before.links != 1
                    or before.attributes & 0x400 or not length
                    or not kernel32.GetFinalPathNameByHandleW(handle, final, len(final), 0)
                    or pathlib.Path(final.value.removeprefix("\\\\?\\")).resolve(strict=False)
                    != path.resolve(strict=True)):
                refuse("held snapshot deletion handle identity/path differs")
            self.crash_hook(f"before_{kind}_tombstone_rename")
            after = FILE_INFO()
            if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(after)) or \
                    (before.volume, before.index_high, before.index_low) != \
                    (after.volume, after.index_high, after.index_low):
                refuse("held snapshot deletion identity changed")
            self.crash_hook(f"after_{kind}_tombstone_rename")
            self.crash_hook(f"before_{kind}_tombstone_delete")
            disposition = wintypes.DWORD(0x1 | 0x2 | 0x10)
            if not kernel32.SetFileInformationByHandle(handle, 21, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                refuse("handle-bound snapshot disposition failed")
            self.crash_hook(f"after_{kind}_tombstone_delete")
        finally:
            kernel32.CloseHandle(handle)

    def _read_json(self, path: pathlib.Path) -> dict[str, Any]:
        before = self._secure(path, regular=True)
        try:
            value = json.loads(self._stable_bytes(path).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            refuse(f"durable store contains torn/invalid {path.name}: {type(error).__name__}")
        if not isinstance(value, dict):
            refuse("durable store JSON is not an object")
        after = self._secure(path, regular=True)
        if (before.get("device"), before.get("identity")) != (after.get("device"), after.get("identity")):
            refuse("protected file identity changed while reading")
        return value

    def _stable_bytes(self, path: pathlib.Path) -> bytes:
        if os.name == "nt":
            return self._windows_stable_bytes(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                refuse("protected artifact handle is not one regular file identity")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk: break
                chunks.append(chunk)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
                refuse("protected artifact identity changed while held open")
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _windows_stable_bytes(self, path: pathlib.Path) -> bytes:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR,
                                                       wintypes.DWORD, wintypes.DWORD)
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel32.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,); kernel32.CloseHandle.restype = wintypes.BOOL
        class DIR_INFO(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("creation_low", wintypes.DWORD),
                        ("creation_high", wintypes.DWORD), ("access_low", wintypes.DWORD),
                        ("access_high", wintypes.DWORD), ("write_low", wintypes.DWORD),
                        ("write_high", wintypes.DWORD), ("volume", wintypes.DWORD),
                        ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                        ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
        ancestor_handles = []
        for ancestor in reversed(path.resolve(strict=True).parents):
            if not ancestor.exists(): continue
            directory_handle = kernel32.CreateFileW(str(ancestor), 0x80000000, 0x1 | 0x2, None, 3,
                                                     0x02000000 | 0x00200000, None)
            if directory_handle == wintypes.HANDLE(-1).value:
                for held, *_ in ancestor_handles: kernel32.CloseHandle(held)
                refuse("unable to hold protected artifact ancestor directory")
            facts = self.security_probe(ancestor)
            within_base = ancestor == self.base or self.base in ancestor.parents
            trusted = facts.get("owner_only", False) if within_base or self.custom_security_probe else \
                _windows_owner_protected_dacl(ancestor, require_current_owner=False, require_protected=False)
            if facts.get("reparse") or not trusted:
                kernel32.CloseHandle(directory_handle)
                for held, *_ in ancestor_handles: kernel32.CloseHandle(held)
                refuse("protected artifact ancestor DACL/owner differs while held")
            info = DIR_INFO(); length = kernel32.GetFinalPathNameByHandleW(directory_handle, None, 0, 0)
            final_buffer = ctypes.create_unicode_buffer(length + 1)
            if (not kernel32.GetFileInformationByHandle(directory_handle, ctypes.byref(info)) or not length
                    or not kernel32.GetFinalPathNameByHandleW(directory_handle, final_buffer, len(final_buffer), 0)
                    or pathlib.Path(final_buffer.value.removeprefix("\\\\?\\")).resolve(strict=False)
                    != ancestor.resolve(strict=True)):
                kernel32.CloseHandle(directory_handle)
                for held, *_ in ancestor_handles: kernel32.CloseHandle(held)
                refuse("protected artifact ancestor handle identity/final path differs")
            ancestor_handles.append((directory_handle, info, final_buffer.value))
        handle = kernel32.CreateFileW(str(path), 0x80000000, 0x1, None, 3, 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            for held, *_ in ancestor_handles: kernel32.CloseHandle(held)
            refuse("unable to open protected artifact without following reparse points")
        try:
            length = kernel32.GetFinalPathNameByHandleW(handle, None, 0, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            if not length or not kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0):
                refuse("unable to resolve protected artifact final handle path")
            final = buffer.value.removeprefix("\\\\?\\")
            if pathlib.Path(final).resolve(strict=False) != path.resolve(strict=True):
                refuse("protected artifact final handle path differs")
            class FILE_INFO(ctypes.Structure):
                _fields_ = [("attributes", wintypes.DWORD), ("creation_low", wintypes.DWORD),
                            ("creation_high", wintypes.DWORD), ("access_low", wintypes.DWORD),
                            ("access_high", wintypes.DWORD), ("write_low", wintypes.DWORD),
                            ("write_high", wintypes.DWORD), ("volume", wintypes.DWORD),
                            ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                            ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
            before = FILE_INFO()
            if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(before)) or before.links != 1 \
                    or before.attributes & 0x400:
                refuse("protected artifact handle identity/reparse/link count differs")
            chunks = []
            while True:
                chunk = ctypes.create_string_buffer(1024 * 1024); read = wintypes.DWORD()
                if not kernel32.ReadFile(handle, chunk, len(chunk), ctypes.byref(read), None):
                    refuse("protected artifact held-handle read failed")
                if read.value == 0: break
                chunks.append(chunk.raw[:read.value])
            after = FILE_INFO(); kernel32.GetFileInformationByHandle(handle, ctypes.byref(after))
            if (before.volume, before.index_high, before.index_low, before.size_high, before.size_low) != \
                    (after.volume, after.index_high, after.index_low, after.size_high, after.size_low):
                refuse("protected artifact volume/file identity changed while held")
            return b"".join(chunks)
        finally:
            kernel32.CloseHandle(handle)
            for held, before_info, before_final in reversed(ancestor_handles):
                after_info = DIR_INFO(); length = kernel32.GetFinalPathNameByHandleW(held, None, 0, 0)
                final_buffer = ctypes.create_unicode_buffer(length + 1)
                valid = (kernel32.GetFileInformationByHandle(held, ctypes.byref(after_info)) and length
                         and kernel32.GetFinalPathNameByHandleW(held, final_buffer, len(final_buffer), 0)
                         and (before_info.volume, before_info.index_high, before_info.index_low, before_final)
                         == (after_info.volume, after_info.index_high, after_info.index_low, final_buffer.value))
                kernel32.CloseHandle(held)
                if not valid: refuse("protected artifact ancestor identity changed while leaf was read")

    def _load_unlocked(self) -> dict[str, Any]:
        self.initialize()
        self._recover()
        envelope = self._read_json(self.envelope_path)
        if set(envelope) != {"schema_version", "operation_id", "journal", "nonces"} \
                or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 2 or envelope["operation_id"] != self.operation_id:
            refuse("durable broker envelope differs")
        journal = envelope["journal"]
        MODEL.validate_journal(journal)
        if journal["operation_id"] != self.operation_id:
            refuse("stored journal operation differs")
        expected_nonces = [entry["cas_nonce"] for entry in journal["history"]]
        if envelope["nonces"] != expected_nonces or len(expected_nonces) != len(set(expected_nonces)):
            refuse("envelope nonce ledger does not exactly replay journal history")
        return journal

    def load(self) -> dict[str, Any]:
        with self.locked():
            return self._load_unlocked()

    def _recover(self) -> None:
        if not self.temp_path.exists():
            return
        staged = self._read_json(self.temp_path)
        self._validate_envelope(staged, "staged")
        if self.envelope_path.exists():
            current = self._read_json(self.envelope_path)
            self._validate_envelope(current, "current")
            current_journal, staged_journal = current["journal"], staged["journal"]
            if staged_journal["generation"] == current_journal["generation"] + 1:
                if canonical_bytes(staged_journal["history"][:-1]) != canonical_bytes(current_journal["history"]):
                    refuse("staged recovery envelope forks current ancestry")
                chosen = staged
            elif staged_journal["generation"] <= current_journal["generation"]:
                chosen = current
            else:
                refuse("staged recovery envelope skips current generation")
        else:
            staged_journal = staged["journal"]
            if (type(staged_journal["generation"]) is not int or type(staged_journal["lease_epoch"]) is not int
                    or staged_journal["generation"] != 1 or staged_journal["lease_epoch"] < 1
                    or len(staged_journal["history"]) != 1
                    or staged_journal["history"][0]["event"] != "START_SPEC"):
                refuse("orphan staged envelope is not exact START_SPEC genesis")
            chosen = staged
        self._replace(self.temp_path, self.envelope_path) if chosen is staged else self.temp_path.unlink()
        if os.name != "nt":
            directory = os.open(self.root, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)

    def _validate_envelope(self, value: dict[str, Any], label: str) -> None:
        if (set(value) != {"schema_version", "operation_id", "journal", "nonces"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 2 or value["operation_id"] != self.operation_id):
            refuse(f"{label} envelope manifest differs")
        MODEL.validate_journal(value["journal"])
        exact_nonces = [entry["cas_nonce"] for entry in value["journal"]["history"]]
        if value["nonces"] != exact_nonces:
            refuse(f"{label} envelope nonce ancestry differs")

    def _replace(self, source: pathlib.Path, target: pathlib.Path) -> None:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.MoveFileExW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
            kernel32.MoveFileExW.restype = wintypes.BOOL
            if not kernel32.MoveFileExW(str(source), str(target), 0x1 | 0x8):
                refuse("durable Windows atomic replace failed")
        else:
            os.replace(source, target)

    def _atomic(self, path: pathlib.Path, value: dict[str, Any], temp: pathlib.Path) -> None:
        raw = canonical_bytes(value) + b"\n"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if os.name == "nt":
                _protect_windows_path(temp)
            write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.crash_hook("after_temp_fsync")
        self._replace(temp, path)
        if os.name == "nt":
            _protect_windows_path(path)
        self.crash_hook("after_replace")
        if os.name != "nt":
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        self.crash_hook("after_directory_fsync")

    def _atomic_snapshot_file(self, final: pathlib.Path, raw: bytes, *, kind: str) -> None:
        temp = self.root / f".phase6-{kind}-{secrets.token_hex(16)}.tmp"
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            _protect_windows_path(temp); self.crash_hook(f"after_{kind}_create")
            write_all(descriptor, raw); self.crash_hook(f"after_{kind}_partial_write")
            os.fsync(descriptor); self.crash_hook(f"after_{kind}_fsync")
        finally:
            os.close(descriptor)
        self._secure(temp, regular=True)
        observed_temp = self._stable_bytes(temp)
        if observed_temp != raw: refuse(f"protected {kind} temporary bytes differ")
        self._replace(temp, final); self.crash_hook(f"after_{kind}_replace")
        self._secure(final, regular=True)
        if self._stable_bytes(final) != raw: refuse(f"committed {kind} bytes differ")

    def cas(self, journal: dict[str, Any], *, expected_generation: int, expected_lease_epoch: int,
            expected_cas_nonce: str | None, expected_head_sha256: str | None) -> dict[str, Any]:
        MODEL.validate_journal(journal)
        if (type(expected_generation) is not int or type(expected_lease_epoch) is not int
                or isinstance(expected_generation, bool) or isinstance(expected_lease_epoch, bool)):
            refuse("store CAS scalar types differ")
        if journal["operation_id"] != self.operation_id:
            refuse("CAS operation differs")
        with self.locked():
            self.initialize()
            current = self._load_unlocked() if self.envelope_path.exists() or self.temp_path.exists() else None
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
            current = self._load_unlocked()
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

    def verify_admission(self, *, authorization_path: pathlib.Path, artifacts: dict[str, pathlib.Path]) -> dict[str, Any]:
        mapping = {"broker": "broker_sha256", "policy": "transaction_policy_sha256",
                   "rollback_policy": "rollback_policy_sha256", "contract": "contract_sha256",
                   "tool_lock": "tool_lock_sha256", "security_review": "security_review_sha256",
                   "reliability_review": "reliability_review_sha256", "user_approval": "user_approval_sha256",
                   "plan": "plan_sha256", "pre_backup": "etcd_backup_sha256",
                   "post_backup": "data_backup_sha256", "preflight": "preflight_sha256",
                   "cost": "cost_sha256", "capacity": "capacity_sha256", "collector": "collector_sha256",
                   "provider_facts": "provider_facts_sha256", "journal": "journal_sha256"}
        required = set(mapping) | {"state_receipt"}
        if not isinstance(self.verifier, CheckedInAuthorizationVerifier) and not self.allow_test_verifier:
            refuse("production admission requires the checked-in authorization verifier adapter")
        auth_before = self._secure(authorization_path, regular=True)
        authorization_raw = self._stable_bytes(authorization_path)
        auth_after = self._secure(authorization_path, regular=True)
        if (auth_before.get("device"), auth_before.get("identity")) != \
                (auth_after.get("device"), auth_after.get("identity")):
            refuse("authorization artifact identity changed while held")
        try:
            authorization = json.loads(authorization_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            refuse("held authorization artifact bytes are invalid")
        schema_path = HERE.parents[1] / "schemas" / "phase6-github-authorization.schema.json"
        schema_raw = self._stable_bytes(schema_path)
        if digest_bytes(schema_raw) != AUTHORIZATION_SCHEMA_SHA256:
            refuse("authorization schema hash differs from compiled admission boundary")
        try:
            from jsonschema import Draft202012Validator
            Draft202012Validator(json.loads(schema_raw)).validate(authorization)
        except Exception as error:
            refuse(f"held authorization artifact fails Draft 2020-12 schema: {type(error).__name__}")
        if (not isinstance(authorization, dict) or set(authorization) != AUTHORIZATION_KEYS
                or type(authorization.get("schema_version")) is not int or type(authorization.get("phase")) is not int
                or authorization.get("schema_version") != 1 or authorization.get("phase") != 6
                or authorization.get("status") != "GITHUB_PROTECTED_MAIN_AUTHORIZED"
                or authorization.get("authorization_mode") != "TRANSACTION"
                or authorization.get("journal_state") != "AUTHORIZED"
                or authorization.get("security_approved") is not True
                or authorization.get("reliability_approved") is not True
                or authorization.get("raw_values_recorded") is not False):
            refuse("held authorization artifact schema differs")
        if (set(artifacts) != required or self.verifier is None
                or authorization.get("operation_id") != self.operation_id
                or any(not DIGEST.fullmatch(authorization.get(field, "")) for field in mapping.values())):
            refuse("admission artifact/hash/verifier boundary differs")
        receipt = self.verifier.verify(authorization_path, authorization_raw, authorization)
        if (not isinstance(receipt, dict) or set(receipt) != VERIFIER_RECEIPT_KEYS
                or receipt.get("status") != "GITHUB_TRANSACTION_AUTHORIZATION_VERIFIED_DORMANT"
                or receipt.get("requires_reverification_before_use") is not True
                or receipt.get("operation_id") != self.operation_id
                or receipt.get("authorization_sha256") != digest_bytes(authorization_raw)
                or not MODEL.COMMIT.fullmatch(receipt.get("authorization_commit", ""))
                or not DIGEST.fullmatch(receipt.get("authorization_history_sha256", ""))
                or receipt.get("source_parent_commit") != authorization.get("source_parent_commit")
                or receipt.get("workflow_id") != authorization.get("workflow_id")
                or receipt.get("pr_number") != authorization.get("pr_number")
                or receipt.get("complete_by") != authorization.get("complete_by")):
            refuse("direct synchronous authorization verifier receipt differs")
        measured: dict[str, str] = {}
        for name in sorted(mapping):
            path = artifacts[name]
            before = self._secure(path, regular=True)
            measured[name] = digest_bytes(self._stable_bytes(path))
            after = self._secure(path, regular=True)
            if (before.get("device"), before.get("identity")) != (after.get("device"), after.get("identity")):
                refuse(f"admission {name} identity changed during hash")
            if measured[name] != authorization[mapping[name]]:
                refuse(f"admission {name} hash differs")
        state_receipt = self._read_json(artifacts["state_receipt"])
        if (set(state_receipt) != {"state_lineage_sha256", "state_serial", "canonical_state_path",
                                  "raw_values_recorded"}
                or state_receipt["state_lineage_sha256"] != authorization.get("state_lineage_sha256")
                or state_receipt["state_serial"] != authorization.get("state_serial")
                or pathlib.Path(state_receipt["canonical_state_path"]).resolve(strict=False) != self.state_path
                or state_receipt["raw_values_recorded"] is not False):
            refuse("admission state receipt differs from authorization")
        measured["state_receipt"] = digest_bytes(canonical_bytes(state_receipt))
        return {"operation_id": self.operation_id, "measured_hashes": measured,
                "verifier_receipt_sha256": digest_bytes(canonical_bytes(receipt)),
                "observed_at": utc_text(self.clock()), "raw_values_recorded": False}


class ReadOnlyAdmissionAdapter:
    def __init__(self, store: DurableBrokerStore,
                 runner: Callable[[tuple[str, ...]], tuple[int, str, str]], clock: Callable[[], dt.datetime]) -> None:
        self.store, self.runner, self.clock = store, runner, clock

    def collect(self, kind: str) -> dict[str, Any]:
        if kind not in READ_ONLY_COMMANDS:
            refuse("read-only adapter command is not fixed/allowed")
        command = READ_ONLY_COMMANDS[kind]
        snapshot_digest = None
        if kind == "terraform-state":
            with self.store.locked():
                self.store.initialize()
                self.store._recover_stale_snapshots()
                self.store._secure(self.store.state_path, regular=True)
                raw = self.store._stable_bytes(self.store.state_path)
                snapshot_digest = digest_bytes(raw)
                snapshot = self.store.root / f"state-{snapshot_digest}-{secrets.token_hex(16)}.read-only.tfstate"
                marker = snapshot.with_name(snapshot.name + ".manifest.json")
                manifest = {"schema_version": 1, "operation_id": self.store.operation_id,
                            "snapshot_name": snapshot.name, "snapshot_sha256": snapshot_digest, "state": "PLANNED",
                            "created_at": utc_text(self.clock()), "raw_values_recorded": False}
                self.store._atomic_snapshot_file(marker, canonical_bytes(manifest) + b"\n", kind="intent")
                self.store._atomic_snapshot_file(snapshot, raw, kind="snapshot")
                self.store._secure(snapshot, regular=True)
                if self.store._stable_bytes(snapshot) != raw:
                    snapshot.unlink(missing_ok=True)
                    refuse("protected Terraform snapshot bytes differ")
                try:
                    command = command + (str(snapshot),)
                    started = self.clock(); code, stdout, stderr = self.runner(command); ended = self.clock()
                finally:
                    self.store._delete_windows_write_through(snapshot, original_name=snapshot.name)
                    self.store._delete_windows_write_through(marker, original_name=marker.name)
        else:
            started = self.clock(); code, stdout, stderr = self.runner(command); ended = self.clock()
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
            ready = 0
            for item in items:
                conditions = item.get("status", {}).get("conditions") if isinstance(item, dict) else None
                if not isinstance(conditions, list): refuse("Kubernetes Ready condition list differs")
                matches = [condition for condition in conditions if isinstance(condition, dict)
                           and condition.get("type") == "Ready"]
                if len(matches) != 1 or matches[0].get("status") not in {"True", "False", "Unknown"}:
                    refuse("Kubernetes Ready condition differs")
                ready += matches[0]["status"] == "True"
            aggregate = {"member_count": len(items), "ready_count": ready}
        elif kind == "provider-inventory":
            items = parsed.get("instances")
            if not isinstance(items, list): refuse("provider inventory aggregate schema differs")
            statuses = {"running": 0, "stopped": 0, "other": 0}; types: dict[str, int] = {}
            for item in items:
                if (not isinstance(item, dict) or not isinstance(item.get("status"), str)
                        or not isinstance(item.get("instance_type"), str)):
                    refuse("provider inventory instance aggregate fields differ")
                status = item["status"].lower()
                statuses[status if status in {"running", "stopped"} else "other"] += 1
                types[item["instance_type"]] = types.get(item["instance_type"], 0) + 1
            aggregate = {"instance_count": len(items), "status_counts": statuses,
                         "instance_type_counts": dict(sorted(types.items()))}
        else:
            values = parsed.get("values")
            if not isinstance(values, dict): refuse("Terraform state aggregate schema differs")
            def count_module(module: object) -> int:
                if not isinstance(module, dict): refuse("Terraform module aggregate schema differs")
                resources, children = module.get("resources", []), module.get("child_modules", [])
                if not isinstance(resources, list) or not all(isinstance(item, dict) for item in resources) \
                        or not isinstance(children, list):
                    refuse("Terraform resource/child module aggregate schema differs")
                return len(resources) + sum(count_module(child) for child in children)
            aggregate = {"resource_count": count_module(values.get("root_module"))}
        sanitized = {"kind": kind, "command_sha256": digest_bytes(canonical_bytes(command)),
                     "started_at": utc_text(started), "ended_at": utc_text(ended),
                     "duration_ms": int(duration * 1000), "freshness_seconds": 10,
                     "aggregate": aggregate, "raw_values_recorded": False}
        if kind == "terraform-state":
            sanitized["state_snapshot_sha256"] = snapshot_digest
            sanitized["canonical_state_path"] = str(self.store.state_path)
        return sanitized


def main() -> int:
    print("REFUSED: durable Phase 6 broker store has no effect adapter or execution route", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
