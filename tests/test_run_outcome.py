"""Exit codes, protected dashboard and cache, opt-in AI with a per-run limit, concurrent runs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_analyzer
import main
import run_lock
import setup_panel
import startup_config
from exit_codes import EXIT_BUSY, EXIT_FAILURE, EXIT_PARTIAL, EXIT_SUCCESS
from job_model import normalize_job
from scrapers.site_report import RunReport

PROJECT_DIR = Path(__file__).resolve().parent.parent


LISTING_TEXT = "Sviluppo di servizi in Python per i clienti dell'azienda, in un piccolo team di prodotto."


def _raw(url: str = "https://example.ch/1", title: str = "Sviluppatore Python", **extra: object) -> dict:
    base = {"title": title, "company": "ACME SA", "city": "Chiasso", "date": "2026-11-05", "url": url,
            "source": "jobs.ch"}
    base.update(extra)
    return base


def _report_with(monkeypatch, *results: tuple[str, int, str]) -> RunReport:
    report = RunReport()
    for site, jobs, status in results:
        report.finish(site, jobs, 1.0, status=status)
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda *_: None)
    return report


def _args(**changes: object) -> SimpleNamespace:
    values = {"dry_run": False, "scan_only": False, "reanalyze": False, "background": True}
    values.update(changes)
    return SimpleNamespace(**values)


# --- exit codes ----------------------------------------------------------------------------

@pytest.mark.parametrize(("results", "expected"), [
    ([("a", 5, "ok"), ("b", 0, "no_results")], EXIT_SUCCESS),
    ([("a", 5, "ok"), ("b", 0, "timeout")], EXIT_PARTIAL),
    ([("a", 5, "ok_partial")], EXIT_PARTIAL),
    ([("a", 0, "timeout"), ("b", 0, "blocked")], EXIT_FAILURE),
])
def test_exit_code_after_a_completed_scan(monkeypatch, results, expected) -> None:
    _report_with(monkeypatch, *results)
    assert main._exit_code_after_run(_args(), [normalize_job(_raw())]) == expected


def test_an_interrupted_scan_is_never_reported_as_a_clean_success(monkeypatch) -> None:
    _report_with(monkeypatch, ("a", 5, "ok"))
    assert main._exit_code_after_run(_args(), None) == EXIT_PARTIAL


def test_a_dry_run_reports_the_state_of_the_portals(monkeypatch) -> None:
    _report_with(monkeypatch, ("a", 0, "ok"), ("b", 0, "blocked"))
    assert main._exit_code_after_run(_args(dry_run=True), None) == EXIT_PARTIAL


def test_a_run_that_produced_no_report_and_no_jobs_is_a_failure(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_report", RunReport())
    assert main._exit_code_after_run(_args(), None) == EXIT_FAILURE


def test_a_reanalysis_without_a_scan_is_a_success(monkeypatch) -> None:
    monkeypatch.setattr(main, "run_report", RunReport())
    assert main._exit_code_after_run(_args(reanalyze=True), []) == EXIT_SUCCESS


def test_main_exits_with_the_code_of_the_run(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "_parse_args", lambda: SimpleNamespace(
        project_dir=False, headless=False, timeout=0, auth="", background=True, ai=False, reanalyze=False))
    monkeypatch.setattr(main, "_setup_search", lambda *_: True)
    monkeypatch.setattr(main, "_run_locked", lambda *_: EXIT_PARTIAL)
    monkeypatch.setattr(main, "LOCK_FILE", tmp_path / ".jobscraper.lock")

    with pytest.raises(SystemExit) as stop:
        main.main()

    assert stop.value.code == EXIT_PARTIAL
    assert not (tmp_path / ".jobscraper.lock").exists()
    assert "partial" in capsys.readouterr().out


# --- a failed scan keeps the previous results --------------------------------------------

def test_when_every_source_fails_cache_and_dashboard_stay_untouched(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "jobs_cache.json"
    cache.write_text('[{"keep": "me"}]', encoding="utf-8")
    dashboard = tmp_path / "index.html"
    dashboard.write_text("<html>previous dashboard</html>", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    _report_with(monkeypatch, ("jobs.ch", 0, "timeout"), ("indeed.it", 0, "blocked"))

    result = main._finish_scrape_run([normalize_job(_raw())], True)

    assert result is None
    assert cache.read_text(encoding="utf-8") == '[{"keep": "me"}]'
    assert dashboard.read_text(encoding="utf-8") == "<html>previous dashboard</html>"
    assert not (tmp_path / "jobs_cache.partial.json").exists()


def test_a_partial_scan_still_saves_what_was_read_with_the_saved_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "jobs_cache.json"
    cache.write_text(json.dumps([_raw("https://example.ch/old", "Old job", source="indeed.it")]), encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    _report_with(monkeypatch, ("jobs.ch", 1, "ok"), ("indeed.it", 0, "blocked"))
    jobs = main._build_job_list([_raw("https://example.ch/new", "New job")], False)

    result = main._finish_scrape_run(jobs, True)

    statuses = {job["title"]: job["status"] for job in result}
    assert statuses == {"Old job": "cached_source_unavailable", "New job": "active"}
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2


# --- AI is opt-in and capped -------------------------------------------------------------

def test_the_ai_is_off_when_the_program_starts() -> None:
    code = "import main; print(main._AI_ENABLED)"
    result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_DIR, capture_output=True, text=True, check=True,
                            env={**os.environ, "OPENAI_API_KEY": "present-but-not-an-opt-in"})
    assert result.stdout.strip() == "False"


def test_default_settings_keep_the_ai_off_and_capped() -> None:
    settings = startup_config.default_settings(["jobs.ch"], ["python"])
    assert settings["ai_enabled"] is False
    assert 1 <= settings["ai_max_per_run"] <= 50


def test_a_key_in_the_environment_alone_never_calls_the_ai(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "key-in-the-environment")
    monkeypatch.setattr(main, "_AI_ENABLED", False)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main, "CACHE_FILE", tmp_path / "jobs_cache.json")
    monkeypatch.setattr(main, "generate_html", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_open_dashboard", lambda *_: None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the AI must not run when it was not switched on")

    monkeypatch.setattr(main, "analyze_jobs", forbidden)
    monkeypatch.setattr(ai_analyzer, "_create_openai_client", forbidden)

    main._finalize_jobs([normalize_job(_raw())], main.datetime.now())


def test_command_line_flags_are_explicit_opt_ins() -> None:
    assert main._ai_requested_on_command_line(SimpleNamespace(ai=True, reanalyze=False)) is True
    assert main._ai_requested_on_command_line(SimpleNamespace(ai=False, reanalyze=True)) is True
    assert main._ai_requested_on_command_line(SimpleNamespace(ai=False, reanalyze=False)) is False
    assert main._ai_requested_on_command_line(SimpleNamespace()) is False


def test_the_ai_only_rates_visible_jobs_that_are_not_expired(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "_AI_ENABLED", True)
    monkeypatch.setattr(main, "_AI_MAX_PER_RUN", 7)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main, "CACHE_FILE", tmp_path / "jobs_cache.json")
    monkeypatch.setattr(main, "generate_html", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_open_dashboard", lambda *_: None)
    seen: dict = {}

    def fake_analyze(jobs, retry_unanalyzable=False, max_jobs=None):
        seen["titles"] = [job["title"] for job in jobs]
        seen["max_jobs"] = max_jobs
        return jobs

    monkeypatch.setattr(main, "analyze_jobs", fake_analyze)
    visible = normalize_job(_raw("https://example.ch/1", "Visible", description=LISTING_TEXT))
    expired = normalize_job(_raw("https://example.ch/2", "Expired", description=LISTING_TEXT))
    expired["status"] = "possibly_expired"
    hidden = normalize_job(_raw("https://example.ch/3", "Hidden", city="Roma"))

    main._finalize_jobs([visible, expired, hidden], main.datetime.now())

    assert seen == {"titles": ["Visible"], "max_jobs": 7}


class _CountingClient:
    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        self.calls += 1
        answer = json.dumps({"suitable": True, "reason": "fit", "description": "text", "salary": None})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


def test_the_per_run_limit_sends_only_the_newest_listings(monkeypatch) -> None:
    client = _CountingClient()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_analyzer, "_DELAY_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", "Graduate with projects")
    monkeypatch.setattr(ai_analyzer, "_create_openai_client", lambda: client)
    jobs = [normalize_job(_raw(f"https://example.ch/{number}", f"Job {number}", date=f"2026-11-0{number}",
                               description=LISTING_TEXT))
            for number in range(1, 6)]

    ai_analyzer.analyze_jobs(jobs, max_jobs=2)

    assert client.calls == 2
    analysed = sorted(job["title"] for job in jobs if job.get("ai_suitable") is not None)
    assert analysed == ["Job 4", "Job 5"]


def test_without_a_limit_every_pending_job_is_rated(monkeypatch) -> None:
    client = _CountingClient()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_analyzer, "_DELAY_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", "Graduate with projects")
    monkeypatch.setattr(ai_analyzer, "_create_openai_client", lambda: client)
    jobs = [normalize_job(_raw(f"https://example.ch/{number}", f"Job {number}", description=LISTING_TEXT))
            for number in range(1, 4)]

    ai_analyzer.analyze_jobs(jobs)

    assert client.calls == 3


# --- settings written before the limit existed keep working -----------------------------

def test_settings_saved_before_the_ai_limit_existed_are_still_valid(tmp_path) -> None:
    sources = {"jobs.ch"}
    settings = startup_config.default_settings(["jobs.ch"], ["python"])
    del settings["ai_max_per_run"]
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    loaded = startup_config.load_settings(path, sources)

    assert loaded["ai_max_per_run"] == startup_config.DEFAULT_AI_MAX_PER_RUN
    startup_config.validate_settings(settings, sources)  # also valid without the optional key


@pytest.mark.parametrize("value", [0, -1, 201, 1.5, True, "5", None])
def test_an_invalid_ai_limit_is_rejected(value) -> None:
    settings = startup_config.default_settings(["jobs.ch"], ["python"])
    settings["ai_max_per_run"] = value
    with pytest.raises(ValueError):
        startup_config.validate_settings(settings, {"jobs.ch"})


# --- concurrent runs -------------------------------------------------------------------

def test_a_second_run_in_the_same_folder_exits_busy_and_changes_nothing(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    lock = tmp_path / ".jobscraper.lock"
    monkeypatch.setattr(main, "LOCK_FILE", lock)
    monkeypatch.setattr(main, "_parse_args", lambda: SimpleNamespace(
        project_dir=False, headless=False, timeout=0, auth="", background=True, ai=False, reanalyze=False))
    monkeypatch.setattr(main, "_setup_search", lambda *_: True)

    def must_not_run(*_):
        raise AssertionError("a second scan must not start")

    monkeypatch.setattr(main, "_run_locked", must_not_run)

    with run_lock.exclusive_run(lock):
        with pytest.raises(SystemExit) as stop:
            main.main()

    assert stop.value.code == EXIT_BUSY
    assert "already running" in capsys.readouterr().out


# --- the panel shows the same outcome ----------------------------------------------------

@pytest.mark.parametrize(("code", "status"), [
    (EXIT_SUCCESS, "complete"), (EXIT_PARTIAL, "partial"), (EXIT_BUSY, "busy"), (EXIT_FAILURE, "error"), (99, "error"),
])
def test_the_panel_status_matches_the_exit_code(code: int, status: str) -> None:
    assert setup_panel.status_for_exit_code(code) == status


def test_the_panel_refuses_to_start_while_another_scan_holds_the_lock(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(setup_panel, "LOCK_PATH", tmp_path / ".jobscraper.lock")
    monkeypatch.setattr(startup_config, "SETTINGS_FILE", tmp_path / "user_settings.json")
    settings = startup_config.default_settings(["jobs.ch"], ["python"])
    server = setup_panel.LocalPanelServer(settings, {"jobs.ch"})
    try:
        with run_lock.exclusive_run(tmp_path / ".jobscraper.lock"):
            with pytest.raises(ValueError, match="already running"):
                server.start(settings)
    finally:
        server.server_close()


def test_a_large_log_is_rotated_and_a_small_one_is_left_alone(tmp_path) -> None:
    log = tmp_path / "scraper.log"
    log.write_text("x" * 10, encoding="utf-8")
    setup_panel.rotate_log_if_large(log, max_bytes=100)
    assert log.exists()

    log.write_text("x" * 500, encoding="utf-8")
    setup_panel.rotate_log_if_large(log, max_bytes=100)
    assert not log.exists()
    assert (tmp_path / "scraper.log.old").read_text(encoding="utf-8") == "x" * 500

    setup_panel.rotate_log_if_large(tmp_path / "missing.log", max_bytes=100)  # no log yet: nothing to do


def test_listings_whose_description_waits_for_the_next_run_cannot_be_rated_yet(monkeypatch) -> None:
    monkeypatch.setattr(main, "MAX_DESCRIPTIONS_PER_RUN", 2)
    monkeypatch.setattr(main, "_PREFERENCES", main.SearchPreferences())
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)

    def fake_fetch(_context, _url):
        return {"description": LISTING_TEXT, "email": ""}

    monkeypatch.setattr(main, "fetch_description", fake_fetch)
    jobs = [normalize_job(_raw(f"https://example.ch/{number}", f"Job {number}")) for number in range(1, 5)]

    main._download_descriptions(None, jobs)

    can_be_rated = [job["title"] for job in jobs if ai_analyzer.has_listing_text(job)]
    assert can_be_rated == ["Job 1", "Job 2"]


def test_a_job_that_already_has_its_description_is_rated(monkeypatch) -> None:
    job = normalize_job(_raw(description="A long description of the work and the team."))
    assert main._jobs_worth_analyzing([job]) == [job]
