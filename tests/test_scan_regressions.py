"""Regression tests for partial scans and search completeness."""

import json
from types import SimpleNamespace

import pytest

import main
from ai_analyzer import _apply_llm_result
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

    result = main._finish_scrape_run([new_job], [], "", True)

    assert {item["title"] for item in result} == {"Old", "New"}
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2


def test_incomplete_scan_does_not_overwrite_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache.json"
    cache.write_text("original", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    report = RunReport()
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(report, "save", lambda: None)

    result = main._finish_scrape_run([job("x", "https://x.ch/1", "New")], [], "", False)

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

    main._finish_scrape_run([job("x", "https://x.ch/1", "New")], [], "", True, True)

    assert cache.read_text(encoding="utf-8") == "original"


def test_duplicate_page_does_not_stop_pagination():
    existing = job("jobs.ch", "https://jobs.ch/1", "Existing")
    jobs = []
    assert _add_new_jobs([existing], 2, {existing["url"]}, jobs) is True
    assert jobs == []


@pytest.mark.parametrize("value", [None, "false", 0, 1])
def test_ai_suitability_requires_boolean(value):
    with pytest.raises(ValueError):
        _apply_llm_result({}, {"suitable": value})


def test_corrupt_cache_is_not_treated_as_empty(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(main, "CACHE_FILE", cache)

    with pytest.raises(json.JSONDecodeError):
        main._read_cache_or_empty()
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
    args = SimpleNamespace(project_dir=True, headless=False, timeout=0, auth="")
    monkeypatch.setattr(main, "_parse_args", lambda: args)
    monkeypatch.setattr(main, "_run_scan_mode", lambda *_: None)

    main.main()

    assert main.Path.cwd() == main.Path(main.__file__).resolve().parent
