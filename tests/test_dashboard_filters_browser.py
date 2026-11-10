"""Search, filters, sorting, themes and keyboard use of the dashboard, in a real Chromium.

Every listing here is invented for the test. See tests/conftest.py for the browser fixture.
"""

from pathlib import Path

import pytest

import dashboard_builder
from job_model import normalize_job

MOBILE_WIDTH = 375
DESKTOP_WIDTH = 1280


def _listing(title: str, company: str, city: str = "Chiasso", source: str = "jobs.ch", **extra: object) -> dict:
    job = normalize_job({"title": title, "company": company, "city": city, "date": "2026-11-05",
                         "url": f"https://www.{source}/annuncio/{abs(hash(title + company)) % 100000}",
                         "source": source})
    job.update({"status": "active", "last_seen": "2026-11-09T08:00:00", "last_verified": "2026-11-09T08:00:00"})
    job.update(extra)
    return job


SEARCH_JOBS = [
    _listing("Network Engineer", "AT&T Svizzera"),
    _listing("Sviluppatore C# / .NET", "O'Brien & Figli"),
    _listing('Tecnico "Help Desk" 100%', "Società Caffè Però"),
    _listing("<b>Bold</b> Developer", "Müller <script>window.__injected=true</script>"),
    _listing("Magazziniere", "Rossi SA", city="Lugano"),
]


def _open(browser, tmp_path: Path, jobs: list[dict], width: int = DESKTOP_WIDTH, color_scheme: str = "light"):
    output = tmp_path / "index.html"
    dashboard_builder.generate_html(jobs, output)
    context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=color_scheme)
    page = context.new_page()
    problems: list[str] = []

    def record_page_error(error) -> None:
        problems.append(f"pageerror: {error}")

    def record_console_error(message) -> None:
        if message.type == "error":
            problems.append(f"{message.type}: {message.text}")

    page.on("pageerror", record_page_error)
    page.on("console", record_console_error)
    page.add_init_script("window.__injected = false;")
    page.goto(output.as_uri())
    return context, page, problems


def _visible_titles(page) -> list[str]:
    return page.eval_on_selector_all(".card:not([hidden]) .card-title", "titles => titles.map(t => t.textContent)")


def _search(page, query: str) -> list[str]:
    page.fill("#search", query)
    return _visible_titles(page)


@pytest.mark.parametrize(("query", "expected_title"), [
    ("AT&T", "Network Engineer"),
    ("at&t svizzera", "Network Engineer"),
    ("o'brien", "Sviluppatore C# / .NET"),
    ("O'Brien & Figli", "Sviluppatore C# / .NET"),
    ("c# / .net", "Sviluppatore C# / .NET"),
    ("società", "Tecnico \"Help Desk\" 100%"),
    ("CAFFÈ PERÒ", "Tecnico \"Help Desk\" 100%"),
    ('"help desk"', "Tecnico \"Help Desk\" 100%"),
    ("100%", "Tecnico \"Help Desk\" 100%"),
    ("<b>bold</b>", "<b>Bold</b> Developer"),
    ("müller <script>", "<b>Bold</b> Developer"),
    ("lugano", "Magazziniere"),
])
def test_the_search_finds_text_with_symbols_quotes_accents_and_markup(browser, tmp_path, query, expected_title) -> None:
    context, page, problems = _open(browser, tmp_path, SEARCH_JOBS)

    assert _search(page, query) == [expected_title]
    assert page.inner_text("#visible-n") == "1"
    assert page.evaluate("window.__injected") is False
    assert problems == []
    context.close()


@pytest.mark.parametrize("query", ["&amp;", "&#x27;", "&quot;", "&lt;b&gt;", "no-listing-says-this"])
def test_the_search_never_matches_the_escaped_form_of_the_text(browser, tmp_path, query) -> None:
    context, page, _problems = _open(browser, tmp_path, SEARCH_JOBS)

    assert _search(page, query) == []
    assert page.is_visible("#empty")
    context.close()


def test_clearing_the_search_shows_every_listing_again(browser, tmp_path) -> None:
    context, page, _problems = _open(browser, tmp_path, SEARCH_JOBS)
    _search(page, "AT&T")

    assert len(_search(page, "")) == len(SEARCH_JOBS)
    assert not page.is_visible("#empty")
    context.close()


def test_markup_in_a_title_or_company_is_text_in_the_page_and_in_the_attributes(browser, tmp_path) -> None:
    context, page, problems = _open(browser, tmp_path, SEARCH_JOBS)

    assert page.evaluate("window.__injected") is False
    assert page.evaluate("document.querySelectorAll('.card b, .card script, .card img').length") == 0
    search_text = page.get_attribute(".card:nth-of-type(4)", "data-search") or ""
    all_search_text = page.eval_on_selector_all(".card", "cards => cards.map(card => card.dataset.search)")
    assert "at&t svizzera" in " ".join(all_search_text)
    assert "&amp;" not in " ".join(all_search_text) and "&amp;" not in search_text
    assert problems == []
    context.close()


# ---- filters, sorting, themes, keyboard

FILTER_JOBS = [
    _listing("Sviluppatore Python Junior", "Alfa SA", city="Chiasso", source="jobs.ch", date="2026-11-08"),
    _listing("Senior Software Engineer", "Beta SA", city="Lugano", source="jobs.ch", date="2026-11-07"),
    _listing("Magazziniere", "Gamma Srl", city="Como", source="indeed.it", date="2026-11-06"),
    _listing("Cameriere", "Delta Srl", city="Como", source="indeed.it", date="2026-11-05",
             status="possibly_expired", last_verified="2026-11-01T08:00:00"),
    _listing("Elettricista", "Epsilon SA", city="Lugano", source="jobs.ch", date="2026-11-04",
             status="gone"),
]


def _click_chip(page, group: str, value: str) -> None:
    page.click(f'[data-filter="{group}"] .chip[data-value="{value}"]')


def test_each_filter_narrows_the_list_and_filters_combine(browser, tmp_path) -> None:
    context, page, problems = _open(browser, tmp_path, FILTER_JOBS)
    assert "Elettricista" not in _visible_titles(page), "a listing that is gone is not shown by default"
    assert len(_visible_titles(page)) == 4

    _click_chip(page, "category", "tech")
    assert _visible_titles(page) == ["Sviluppatore Python Junior", "Senior Software Engineer"]

    _click_chip(page, "seniority", "junior")
    assert _visible_titles(page) == ["Sviluppatore Python Junior"]

    _click_chip(page, "seniority", "all")
    _click_chip(page, "category", "all")
    _click_chip(page, "country", "IT")
    assert _visible_titles(page) == ["Magazziniere", "Cameriere"]

    _click_chip(page, "status", "possibly_expired")
    assert _visible_titles(page) == ["Cameriere"]

    _click_chip(page, "status", "all")
    _click_chip(page, "country", "all")
    page.select_option("#source", "jobs.ch")
    page.select_option("#place", "Lugano")
    assert _visible_titles(page) == ["Senior Software Engineer"]

    page.fill("#search", "alfa")
    assert _visible_titles(page) == []
    assert page.is_visible("#empty")
    assert page.inner_text("#visible-n") == "0"
    assert problems == []
    context.close()


def test_the_pressed_chip_is_announced_to_assistive_technology(browser, tmp_path) -> None:
    context, page, _problems = _open(browser, tmp_path, FILTER_JOBS)

    _click_chip(page, "category", "tech")

    assert page.get_attribute('[data-filter="category"] .chip[data-value="tech"]', "aria-pressed") == "true"
    assert page.get_attribute('[data-filter="category"] .chip[data-value="all"]', "aria-pressed") == "false"
    context.close()


def test_sorting_by_last_check_and_back_to_newest(browser, tmp_path) -> None:
    context, page, _problems = _open(browser, tmp_path, FILTER_JOBS)
    newest_first = _visible_titles(page)
    assert newest_first[0] == "Sviluppatore Python Junior"

    page.select_option("#sort", "checked")
    assert _visible_titles(page)[-1] == "Cameriere", "the listing checked longest ago comes last"

    page.select_option("#sort", "date")
    assert _visible_titles(page) == newest_first
    context.close()


@pytest.mark.parametrize("width", [MOBILE_WIDTH, DESKTOP_WIDTH])
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_no_horizontal_scroll_and_readable_colours_in_both_themes(browser, tmp_path, width, color_scheme) -> None:
    context, page, problems = _open(browser, tmp_path, FILTER_JOBS + SEARCH_JOBS, width=width,
                                    color_scheme=color_scheme)

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no horizontal scroll"
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    text_colour = page.evaluate("getComputedStyle(document.body).color")
    assert background != text_colour
    is_dark_page = page.evaluate(
        "getComputedStyle(document.body).backgroundColor.match(/\\d+/g).slice(0, 3).every(part => Number(part) < 60)")
    assert is_dark_page is (color_scheme == "dark")
    assert problems == []
    context.close()


def test_the_page_can_be_used_from_the_keyboard(browser, tmp_path) -> None:
    context, page, _problems = _open(browser, tmp_path, FILTER_JOBS)

    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "search"
    page.keyboard.type("magazziniere")
    assert _visible_titles(page) == ["Magazziniere"]

    page.fill("#search", "")
    page.focus('[data-filter="category"] .chip[data-value="tech"]')
    page.keyboard.press("Enter")
    assert _visible_titles(page) == ["Sviluppatore Python Junior", "Senior Software Engineer"]
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none", "the focused control shows a visible outline"

    assert page.locator("h1").count() == 1
    assert page.get_attribute("html", "lang")
    unlabeled = page.evaluate(
        "[...document.querySelectorAll('input, select')].filter(control => control.labels.length === 0).length")
    assert unlabeled == 0
    context.close()


# ---- listings whose text could not be read

LONG_TEXT = " | ".join(f"Paragrafo {number}: sviluppo di servizi in Python per i clienti dell'azienda, in un piccolo "
                       f"team di prodotto." for number in range(1, 41))


@pytest.mark.parametrize("width", [MOBILE_WIDTH, DESKTOP_WIDTH])
def test_a_listing_without_text_says_so_next_to_one_with_a_very_long_text(browser, tmp_path, width) -> None:
    jobs = [_listing("Sviluppatore senza testo", "Alfa SA"),
            _listing("Sviluppatore con testo lungo", "Beta SA", description=LONG_TEXT)]
    context, page, problems = _open(browser, tmp_path, jobs, width=width)

    without_text = page.locator(".card", has_text="Sviluppatore senza testo")
    with_text = page.locator(".card", has_text="Sviluppatore con testo lungo")
    assert "The portal did not give the text of this listing" in without_text.inner_text()
    assert without_text.locator("button").count() == 0, "no expand or translate button without a text"
    assert without_text.locator("a.apply-btn").count() == 1, "the link to the listing is still there"

    closed_height = with_text.locator(".desc-text").bounding_box()["height"]
    with_text.locator('[data-action="expand"]').click()
    assert with_text.locator(".desc-text").bounding_box()["height"] > closed_height * 3
    assert with_text.locator('[data-action="expand"]').inner_text() == "Show less"

    page.fill("#search", "senza testo")
    assert _visible_titles(page) == ["Sviluppatore senza testo"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no horizontal scroll"
    assert problems == []
    context.close()
