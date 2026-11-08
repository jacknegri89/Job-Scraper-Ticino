"""One scan at a time in a folder, without a database or a service.

A scan, a re-analysis and a dry run all write the same files (cache, report, dashboard).
Two of them at once, for example a scheduled task that starts while the panel is searching,
could corrupt them. The first one creates a small lock file; the others stop and say so.

The lock file holds the process number and the start time. A lock left by a crash is
recognised and removed: its process no longer exists, or it is older than MAX_LOCK_HOURS
(which also covers a process number reused by an unrelated program).
"""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = ".jobscraper.lock"
MAX_LOCK_HOURS = 12
# A lock that is still being written by the process that just created it is not stale.
_UNREADABLE_GRACE_SECONDS = 10

_WINDOWS_QUERY_LIMITED = 0x1000
_WINDOWS_STILL_ACTIVE = 259
_WINDOWS_ACCESS_DENIED = 5


class AlreadyRunningError(RuntimeError):
    """Another scan holds the lock in this folder."""


@contextmanager
def exclusive_run(lock_path: Path) -> Iterator[None]:
    """Hold the lock while the block runs; raise AlreadyRunningError if it is taken."""
    _acquire(lock_path)
    try:
        yield
    finally:
        _release(lock_path)


def is_running(lock_path: Path) -> bool:
    """True when a live scan holds the lock (a stale lock does not count)."""
    if not lock_path.exists():
        return False
    return not _is_stale(lock_path)


def _acquire(lock_path: Path) -> None:
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _is_stale(lock_path):
                raise AlreadyRunningError(_busy_message(lock_path)) from None
            _remove_quietly(lock_path)
            continue
        _write_owner(descriptor)
        return
    raise AlreadyRunningError(_busy_message(lock_path))


def _write_owner(descriptor: int) -> None:
    owner = {"pid": os.getpid(), "started": int(time.time())}
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
        json.dump(owner, lock_file)


def _release(lock_path: Path) -> None:
    """Remove the lock only if this process owns it."""
    owner = _read_owner(lock_path)
    if owner is not None and owner.get("pid") == os.getpid():
        _remove_quietly(lock_path)


def _busy_message(lock_path: Path) -> str:
    owner = _read_owner(lock_path) or {}
    pid_text = ""
    if owner.get("pid"):
        pid_text = f" (process {owner['pid']})"
    return f"Another scan is already running{pid_text}. Wait for it to finish; nothing was changed."


def _read_owner(lock_path: Path) -> dict | None:
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_stale(lock_path: Path) -> bool:
    owner = _read_owner(lock_path)
    if owner is None:
        return _older_than(lock_path, _UNREADABLE_GRACE_SECONDS)
    pid = owner.get("pid")
    started = owner.get("started")
    if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(started, (int, float)):
        return True
    if time.time() - started > MAX_LOCK_HOURS * 3600:
        return True
    return not _process_exists(pid)


def _older_than(path: Path, seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime > seconds
    except OSError:
        return True


def _remove_quietly(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_exists(pid)
    return _posix_process_exists(pid)


def _posix_process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _windows_process_exists(pid: int) -> bool:
    # os.kill(pid, 0) is not a harmless check on Windows, so ask the system directly.
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_WINDOWS_QUERY_LIMITED, False, pid)
    if not handle:
        return ctypes.get_last_error() == _WINDOWS_ACCESS_DENIED
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _WINDOWS_STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
