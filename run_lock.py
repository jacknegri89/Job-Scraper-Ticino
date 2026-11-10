"""One scan at a time in a folder, without a database or a service.

A scan, a re-analysis and a dry run all write the same files (cache, report, dashboard).
Two of them at once, for example a scheduled task that starts while the panel is searching,
could corrupt them. The first one creates a small lock file; the others stop and say so.

The lock file holds the process number and the moment that process started, as the
operating system reports it. A lock left by a crash is recognised and removed when its
process no longer exists, or when that number now belongs to a process that started at
another moment (the number was reused by an unrelated program).

The age of a lock never frees it: a scan that is still running keeps its lock for as long
as it runs, also after a night with the computer asleep. When the system cannot say when
a process started, a living process keeps the lock: two scans at once would damage the
files, while a lock nobody owns only needs its file deleted.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = ".jobscraper.lock"
# A lock that is still being written by the process that just created it is not stale.
_UNREADABLE_GRACE_SECONDS = 10

_WINDOWS_QUERY_LIMITED = 0x1000
_WINDOWS_STILL_ACTIVE = 259
_WINDOWS_ACCESS_DENIED = 5

# /proc/<pid>/stat: the fields after the program name; the start time is the 22nd field
# of the whole line and the 20th after the name (see "man 5 proc").
_LINUX_START_TIME_FIELD = 19
_LINUX_BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")
_PS_TIMEOUT_SECONDS = 5


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
    owner = {
        "pid": os.getpid(),
        "started": int(time.time()),
        "process_started": _process_start_token(os.getpid()),
    }
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
    return (f"Another scan is already running{pid_text}. Wait for it to finish; nothing was changed. "
            f"If no scan is running, delete the file {lock_path.name} and start again.")


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
    if not _process_exists(pid):
        return True
    return _is_another_process(pid, owner.get("process_started"))


def _is_another_process(pid: int, recorded_start: object) -> bool:
    """True when the process with this number is proven not to be the one that wrote the lock."""
    current_start = _process_start_token(pid)
    if not recorded_start or current_start is None:
        # Not provable (a lock from an older version, or a system that hides it): the living process keeps the lock.
        return False
    return recorded_start != current_start


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



def _process_start_token(pid: int) -> str | None:
    """When the process started, as text that is the same for its whole life; None if unknown.

    Two processes that get the same number, one after the other, started at different moments.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_start_token(pid)
    if sys.platform.startswith("linux"):
        return _linux_start_token(pid)
    return _ps_start_token(pid)


def _windows_start_token(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_WINDOWS_QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        other_times = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        read_ok = kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(other_times[0]),
                                           ctypes.byref(other_times[1]), ctypes.byref(other_times[2]))
        if not read_ok:
            return None
        return f"{created.dwHighDateTime}-{created.dwLowDateTime}"
    finally:
        kernel32.CloseHandle(handle)


def _linux_start_token(pid: int) -> str | None:
    """Start time in clock ticks since boot, with the boot identifier (ticks restart at every boot)."""
    try:
        stat_line = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        boot_id = _LINUX_BOOT_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    # The program name is in brackets and may itself hold spaces or brackets: split after the last one.
    fields_after_name = stat_line.rpartition(")")[2].split()
    if len(fields_after_name) <= _LINUX_START_TIME_FIELD:
        return None
    return f"{boot_id}-{fields_after_name[_LINUX_START_TIME_FIELD]}"


def _ps_start_token(pid: int) -> str | None:
    """macOS and other systems without /proc: ask "ps" when the process started."""
    try:
        # Fixed program and arguments; the only variable part is a whole number.
        answer = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))],  # noqa: S603, S607
                                capture_output=True, text=True, timeout=_PS_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    start_text = answer.stdout.strip()
    if answer.returncode != 0 or not start_text:
        return None
    return start_text
