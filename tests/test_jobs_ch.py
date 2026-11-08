"""jobs.ch scraper: pagination stop and crash isolation between search terms."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers import jobs_ch


def _job(url: str) -> dict[str, str]:
    return {"title": "Operaio", "url": url}


def _scripted_pages(monkeypatch, pages: list[list[str]]) -> list[int]:
    """Make _add_page_jobs return the given URL lists, one per page; record requested pages."""
    requested: list[int] = []

    def fake_add_page_jobs(_page, _term, page_num, _seen, _all_jobs):
        requested.append(page_num)
        return pages[page_num - 1]

    monkeypatch.setattr(jobs_ch, "_add_page_jobs", fake_add_page_jobs)
    return requested


def test_term_stops_when_portal_repeats_the_same_results(monkeypatch) -> None:
    requested = _scripted_pages(monkeypatch, [["a", "b"], ["a", "b"], ["c"]])

    jobs_ch._scrape_term(object(), "operaio", set(), [])

    assert requested == [1, 2]


def test_term_stops_on_empty_page(monkeypatch) -> None:
    requested = _scripted_pages(monkeypatch, [["a"], []])

    jobs_ch._scrape_term(object(), "operaio", set(), [])

    assert requested == [1, 2]


def test_jobs_found_by_other_terms_do_not_stop_a_term(monkeypatch) -> None:
    # Page 1 only holds jobs already seen for a previous term; page 2 is new.
    requested = _scripted_pages(monkeypatch, [["a"], ["b"], []])

    jobs_ch._scrape_term(object(), "tecnico", {"a"}, [])

    assert requested == [1, 2, 3]


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_each_search_term_gets_its_own_page(monkeypatch) -> None:
    pages: list[_FakePage] = []

    def fake_new_page(_context: object) -> _FakePage:
        page = _FakePage()
        pages.append(page)
        return page

    monkeypatch.setattr(jobs_ch, "new_stealth_page", fake_new_page)
    monkeypatch.setattr(jobs_ch, "_scrape_term", lambda *_args: None)

    jobs_ch.scrape_jobs_ch(object(), ["operaio", "tecnico", "autista"])

    assert len(pages) == 3
    assert all(page.closed for page in pages)
