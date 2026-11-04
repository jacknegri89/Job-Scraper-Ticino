"""Regression tests for partial scans and search completeness."""

import json

import pytest

import main
from ai_analyzer import _apply_llm_result
from scrapers.jobs_ch import _add_new_jobs
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
