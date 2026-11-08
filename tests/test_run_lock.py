"""One scan at a time: lock creation, release, stale locks and the panel check."""

import json
import os
import subprocess
import sys
import time

import pytest

import run_lock
from run_lock import AlreadyRunningError, exclusive_run, is_running

# A process number that does not exist on Windows or Linux.
DEAD_PID = 2_000_000_000


def _write_lock(path, pid: int, started: float) -> None:
    path.write_text(json.dumps({"pid": pid, "started": started}), encoding="utf-8")


def test_the_lock_is_created_while_running_and_removed_afterwards(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        assert lock.exists()
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
        assert is_running(lock) is True
    assert not lock.exists()
    assert is_running(lock) is False


def test_a_second_scan_is_refused_and_leaves_the_first_lock_alone(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        with pytest.raises(AlreadyRunningError, match="already running"):
            with exclusive_run(lock):
                raise AssertionError("the second scan must not start")
        assert lock.exists()
    assert not lock.exists()


def test_the_lock_is_released_when_the_scan_crashes(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with pytest.raises(RuntimeError):
        with exclusive_run(lock):
            raise RuntimeError("crash")
    assert not lock.exists()


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    _write_lock(lock, DEAD_PID, time.time())

    assert is_running(lock) is False
    with exclusive_run(lock):
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_a_lock_of_a_live_process_is_respected(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _write_lock(lock, sleeper.pid, time.time())
        assert is_running(lock) is True
        with pytest.raises(AlreadyRunningError):
            with exclusive_run(lock):
                raise AssertionError("must not start")
    finally:
        sleeper.kill()
        sleeper.wait()


def test_a_very_old_lock_is_stale_even_if_the_process_number_is_in_use(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    too_old = time.time() - (run_lock.MAX_LOCK_HOURS + 1) * 3600
    _write_lock(lock, os.getpid(), too_old)

    assert is_running(lock) is False


@pytest.mark.parametrize("content", ["not json", "[]", '{"pid": "x", "started": 1}', '{"pid": true, "started": 1}'])
def test_a_damaged_old_lock_file_is_stale(tmp_path, content: str) -> None:
    lock = tmp_path / ".jobscraper.lock"
    lock.write_text(content, encoding="utf-8")
    long_ago = time.time() - 3600
    os.utime(lock, (long_ago, long_ago))

    assert is_running(lock) is False
    with exclusive_run(lock):
        assert lock.exists()


def test_a_lock_being_written_right_now_is_not_taken_over(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    lock.write_text("", encoding="utf-8")  # created, owner not written yet

    assert is_running(lock) is True


def test_a_lock_owned_by_someone_else_is_never_removed_by_this_process(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        _write_lock(lock, DEAD_PID + 1, time.time())  # taken over while we were running
    assert lock.exists()


def test_the_message_names_the_running_process(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        with pytest.raises(AlreadyRunningError) as error:
            with exclusive_run(lock):
                pass
    assert str(os.getpid()) in str(error.value)
    assert "nothing was changed" in str(error.value)


def test_two_real_processes_cannot_hold_the_lock_together(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    script = (
        "import sys, time, pathlib, run_lock\n"
        "lock = pathlib.Path(sys.argv[1])\n"
        "with run_lock.exclusive_run(lock):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(5)\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", script, str(lock)], stdout=subprocess.PIPE, text=True,
                              cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(AlreadyRunningError):
            with exclusive_run(lock):
                raise AssertionError("must not start")
    finally:
        holder.kill()
        holder.wait()
    # The holder was killed without cleaning up: its lock is now stale and can be taken over.
    assert is_running(lock) is False
    with exclusive_run(lock):
        pass
