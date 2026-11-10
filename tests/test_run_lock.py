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


THIRTEEN_HOURS_AGO_SECONDS = 13 * 3600


def _write_lock(path, pid: int, started: float, process_started: str | None = None) -> None:
    owner = {"pid": pid, "started": started}
    if process_started is not None:
        owner["process_started"] = process_started
    path.write_text(json.dumps(owner), encoding="utf-8")


def _sleeping_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


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
    sleeper = _sleeping_process()
    try:
        _write_lock(lock, sleeper.pid, time.time())
        assert is_running(lock) is True
        with pytest.raises(AlreadyRunningError):
            with exclusive_run(lock):
                raise AssertionError("must not start")
    finally:
        sleeper.kill()
        sleeper.wait()


def test_an_old_lock_is_respected_while_the_scan_that_wrote_it_is_still_running(tmp_path) -> None:
    """A scan can outlive any time limit (a laptop asleep overnight): age alone never frees its lock."""
    lock = tmp_path / ".jobscraper.lock"
    scan = _sleeping_process()
    try:
        long_ago = time.time() - THIRTEEN_HOURS_AGO_SECONDS
        _write_lock(lock, scan.pid, long_ago, run_lock._process_start_token(scan.pid))

        assert is_running(lock) is True
        with pytest.raises(AlreadyRunningError):
            with exclusive_run(lock):
                raise AssertionError("a second scan must not start next to a live one")
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == scan.pid
    finally:
        scan.kill()
        scan.wait()


def test_a_process_number_reused_by_another_program_does_not_hold_the_lock(tmp_path) -> None:
    """The scan crashed and its number went to another program: that program started at another time."""
    lock = tmp_path / ".jobscraper.lock"
    _write_lock(lock, os.getpid(), time.time(), process_started="started-at-another-time")

    assert is_running(lock) is False
    with exclusive_run(lock):
        assert json.loads(lock.read_text(encoding="utf-8"))["process_started"] != "started-at-another-time"


def test_the_lock_records_when_its_process_started(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        owner = json.loads(lock.read_text(encoding="utf-8"))

    assert owner["process_started"] == run_lock._process_start_token(os.getpid())
    if sys.platform in ("win32", "linux"):
        assert owner["process_started"], "Windows and Linux can always tell when a process started"


def test_the_start_time_of_a_process_is_stable_and_missing_for_a_dead_one() -> None:
    assert run_lock._process_start_token(os.getpid()) == run_lock._process_start_token(os.getpid())
    assert run_lock._process_start_token(DEAD_PID) is None


def test_a_live_process_keeps_the_lock_when_its_start_time_cannot_be_read(tmp_path, monkeypatch) -> None:
    """Old lock files and unusual systems: when in doubt the running scan wins, never two at once."""
    lock = tmp_path / ".jobscraper.lock"
    _write_lock(lock, os.getpid(), time.time() - THIRTEEN_HOURS_AGO_SECONDS)
    assert is_running(lock) is True

    monkeypatch.setattr(run_lock, "_process_start_token", lambda _pid: None)
    _write_lock(lock, os.getpid(), time.time(), process_started="anything")
    assert is_running(lock) is True


def test_the_busy_message_says_how_to_recover_from_a_lock_nobody_owns(tmp_path) -> None:
    lock = tmp_path / ".jobscraper.lock"
    with exclusive_run(lock):
        with pytest.raises(AlreadyRunningError) as error:
            with exclusive_run(lock):
                pass
    assert lock.name in str(error.value)


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
