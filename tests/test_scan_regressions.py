"""Regression tests for partial scans and search completeness."""

import json
from types import SimpleNamespace

import pytest

import main
from ai_analyzer import _apply_validated_result, _validated_salary, validate_response
from scrapers.jobs_ch import _add_new_jobs
from scrapers.frontaliereticino_ch import _parse_date
from scrapers.indeed_ch import _relative_to_date as indeed_date
from scrapers.jobscout24_ch import _relative_to_date as jobscout_date
from scrapers.linkedin_ch import _relative_to_date as linkedin_date
from scrapers.manpower_ch import _parse_date as manpower_date
from scrapers.manpower_ch import _job_from_item as manpower_job
from scrapers.adecco_ch import _job_from_item as adecco_job
from scrapers.site_report import RunReport


def job(source, url, title):
    return {"source": source, "url": url, "title": title, "company": "Example", "city": "Chiasso"}


def test_failed_source_keeps_cached_jobs(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    old_job = job("failed.ch", "https://failed.ch/1", "Old")
    cache.write_text(json.dumps([old_job]), encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    report = RunReport()
    report.finish("failed.ch", 0, 1, status="timeout")
    report.finish("good.ch", 1, 1)
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda: None)
    new_job = job("good.ch", "https://good.ch/1", "New")

    jobs = main._build_job_list([new_job], False)
    result = main._finish_scrape_run(jobs, True)

    assert {item["title"] for item in result} == {"Old", "New"}
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2
    statuses = {item["title"]: item["status"] for item in result}
    assert statuses == {"Old": "cached_source_unavailable", "New": "active"}


def test_incomplete_scan_does_not_overwrite_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache.json"
    cache.write_text("original", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    report = RunReport()
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda: None)

    result = main._finish_scrape_run([job("x", "https://x.ch/1", "New")], False)

    assert result is None
    assert cache.read_text(encoding="utf-8") == "original"
    assert (tmp_path / "jobs_cache.partial.json").exists()


def test_scan_only_does_not_write_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text("original", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    report = RunReport()
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda: None)

    main._finish_scrape_run([job("x", "https://x.ch/1", "New")], True, True)

    assert cache.read_text(encoding="utf-8") == "original"


def test_duplicate_page_does_not_stop_pagination():
    existing = job("jobs.ch", "https://jobs.ch/1", "Existing")
    jobs = []
    assert _add_new_jobs([existing], 2, {existing["url"]}, jobs) is True
    assert jobs == []


@pytest.mark.parametrize("value", [None, "false", 0, 1])
def test_ai_suitability_requires_boolean(value):
    with pytest.raises(ValueError):
        validate_response({"suitable": value}, "CH")


def test_corrupt_cache_is_not_treated_as_empty(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)

    with pytest.raises(json.JSONDecodeError):
        main._read_previous_jobs()
    assert cache.read_text(encoding="utf-8") == "not valid json"


@pytest.mark.parametrize("raw", ["", "not a date", "99/99/2026"])
def test_unknown_posting_dates_are_not_invented(raw):
    assert _parse_date(raw) == ""


def test_posting_date_is_normalized():
    assert _parse_date("04/11/2026") == "2026-11-04"


@pytest.mark.parametrize("parse_date", [indeed_date, jobscout_date, linkedin_date])
@pytest.mark.parametrize("raw", ["", "unknown"])
def test_unknown_relative_dates_are_not_reported_as_today(parse_date, raw):
    assert parse_date(raw) == ""


def test_manpower_unknown_date_is_not_invented():
    assert manpower_date("") == ""
    assert manpower_date("99/99/2026") == ""


def test_missing_dates_in_source_jobs_remain_empty():
    assert manpower_job({}, "Worker", "Chiasso", "https://www.manpower.ch/1")["date"] == ""
    assert adecco_job({}, "123", "Worker")["date"] == ""


def test_project_dir_option_selects_project_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(project_dir=True, headless=False, timeout=0, auth="", background=False)
    monkeypatch.setattr(main, "_parse_args", lambda: args)
    monkeypatch.setattr(main, "_run_scan_mode", lambda *_: None)
    monkeypatch.setattr(main, "_setup_search", lambda *_: True)

    main.main()

    assert main.Path.cwd() == main.Path(main.__file__).resolve().parent


def test_cache_write_failure_preserves_previous_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)

    def fail_replace(*_):
        raise OSError("replace failed")

    monkeypatch.setattr(main.os, "replace", fail_replace)
    with pytest.raises(OSError):
        main._save_cache([job("x", "https://x.ch/1", "New")])
    assert cache.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob(".jobs-cache-*.tmp")) == []


def test_interrupted_site_scan_keeps_jobs_from_completed_sources(monkeypatch):
    jobs = []
    monkeypatch.setattr(main, "_ensure_context_alive", lambda *args: (None, None))
    first_job = job("a", "https://a.ch/1", "First")

    def scrape(*args):
        if args[1] == "a":
            return [first_job]
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "_scrape_site_with_progress", scrape)
    selected = [("A", "a", None), ("B", "b", None)]
    with pytest.raises(KeyboardInterrupt):
        main._scrape_selected_sites(None, None, None, selected, jobs)
    assert jobs == [first_job]


def test_incomplete_scan_only_does_not_report_success(monkeypatch):
    report = RunReport()
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda: None)
    assert main._finish_scrape_run([], False, True) is None


def test_interruption_during_descriptions_keeps_downloaded_details(monkeypatch):
    first_job = job("a", "https://a.ch/1", "First")
    monkeypatch.setattr(main, "create_browser_context", lambda *_: (None, None))
    monkeypatch.setattr(main, "save_session", lambda *_: None)
    monkeypatch.setattr(main, "_close_quietly", lambda *_: None)

    def collect(_playwright, browser, context, _selected, raw_jobs):
        raw_jobs.append(first_job)
        return browser, context

    def interrupt(_context, jobs):
        jobs[0]["description"] = "Downloaded before interruption"
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "_scrape_selected_sites", collect)
    monkeypatch.setattr(main, "_build_job_list", lambda raw_jobs, _scan_only: [dict(raw_jobs[0])])
    monkeypatch.setattr(main, "_download_descriptions", interrupt)
    result, completed = main._collect_with_browser(None, [], False)

    assert completed is False
    assert result[0]["description"] == "Downloaded before interruption"


def test_unknown_site_among_valid_selections_is_rejected():
    with pytest.raises(SystemExit):
        main._select_scrapers("jobs.ch,typo")


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, 10 ** 400])
def test_invalid_salary_is_not_used(value):
    assert _validated_salary({"amount": value, "currency": "CHF", "period": "month"}, "CH") is None


def test_invalid_ai_text_does_not_partially_modify_job():
    item = {}
    with pytest.raises(ValueError):
        _apply_validated_result(item, {"suitable": True, "reason": [], "description": "text", "salary": None}, "key")
    assert item == {}


@pytest.mark.parametrize("text", [
    "Your request has been blocked.",
    "Access Denied | You don't have permission",
    "Pardon Our Interruption",
])
def test_anti_bot_pages_are_never_stored_as_descriptions(text):
    from scrapers import looks_like_block_page

    assert looks_like_block_page(text) is True
    assert main._needs_description({"description": text, "status": "active"}) is True


def test_a_real_description_that_mentions_access_is_kept():
    from scrapers import looks_like_block_page

    long_text = "Gestione degli accessi e dei permessi utente. " * 30
    assert looks_like_block_page(long_text) is False
    assert main._needs_description({"description": long_text, "status": "active"}) is False
