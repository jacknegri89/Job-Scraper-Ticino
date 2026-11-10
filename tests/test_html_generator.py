"""Smoke tests for the dashboard generator."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).parent.parent))

import geo


def load_dashboard_module(monkeypatch: MonkeyPatch) -> ModuleType:
    chiasso = geo.find_place("Chiasso").place
    config = ModuleType("user_config")
    config.HOME_LAT = chiasso.lat
    config.HOME_LNG = chiasso.lng
    config.HOME_CITY = "Test Home"
    monkeypatch.setitem(sys.modules, "user_config", config)

    for module_name in ("distance_calculator", "dashboard_builder"):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    return importlib.import_module("dashboard_builder")


def _job(**extra: object) -> dict:
    base = {
        "title": "Production worker",
        "company": "Rossi SA",
        "city": "Chiasso",
        "date": "2026-06-10",
        "url": "https://www.jobs.ch/it/annuncio/123",
        "category": "production",
        "source": "jobs.ch",
    }
    base.update(extra)
    return base


def test_card_shows_configured_home_distance(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job())

    assert "From Test Home" in card
    assert "0 km" in card
    assert 'data-km="0.0"' in card


def test_card_unknown_city_sorts_last(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(city="Lombardia"))

    assert 'data-km="9999"' in card
    assert "<span class=\"meta-v\">-</span>" in card


def test_card_escapes_html_fields(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(title='<script>alert("x")</script>'))

    assert "<script>alert" not in card
    assert "&lt;script&gt;" in card


def test_business_description_is_not_removed_as_navigation(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(description="Gestione progetti di elettronica e semiconduttori."))
    assert "Gestione progetti di elettronica" in card


def test_card_rejects_non_http_url(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(url="javascript:alert(1)"))

    assert 'href="#"' in card
    assert "javascript:alert" not in card


def test_card_rejects_email_header_injection(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(email="person@example.com?bcc=other@example.com"))
    assert "mailto:" not in card


def test_generate_html_writes_complete_page(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output_path = tmp_path / "index.html"

    dashboard.generate_html(
        [_job(), _job(city="Mendrisio", title="Warehouse worker", category="logistics")],
        output_path,
    )
    page = output_path.read_text(encoding="utf-8")

    assert page.startswith("<!DOCTYPE html>")
    assert "__CARDS__" not in page
    assert "__COUNT__" not in page
    assert page.count("<article") == 2
    assert "Nearest" in page
    assert "Highest net salary" in page


def test_generate_html_with_no_jobs_shows_empty_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output_path = tmp_path / "empty.html"

    dashboard.generate_html([], output_path)
    page = output_path.read_text(encoding="utf-8")

    assert 'class="empty show"' in page
    assert "<b>0</b><span>sources</span>" in page
    assert "fonts.googleapis.com" not in page


def test_card_shows_route_ruler_only_for_known_city(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    known_city_card = dashboard.build_card(_job(city="Mendrisio"))
    unknown_city_card = dashboard.build_card(_job(city="Lombardia"))

    assert 'class="route"' in known_city_card
    assert 'class="route"' not in unknown_city_card


def test_job_text_that_looks_like_a_marker_is_not_replaced(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output_path = tmp_path / "index.html"

    dashboard.generate_html([_job(title="Worker __EMPTY_SUB__ __COUNT__")], output_path)
    page = output_path.read_text(encoding="utf-8")

    assert "Worker __EMPTY_SUB__ __COUNT__" in page


def test_page_blocks_external_resources(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output_path = tmp_path / "index.html"

    dashboard.generate_html([_job()], output_path)
    page = output_path.read_text(encoding="utf-8")

    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page


def test_dashboard_hides_distance_when_home_is_not_configured(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    monkeypatch.setattr(dashboard, "is_home_configured", lambda: False)
    monkeypatch.setattr(dashboard, "km_from_home", lambda *_args: None)
    output_path = tmp_path / "index.html"

    dashboard.generate_html([_job()], output_path)
    page = output_path.read_text(encoding="utf-8")

    assert "From Test Home" not in page
    assert "Nearest" not in page
    assert 'class="route"' not in page


def test_good_match_filter_is_hidden_without_ai_results(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    page_without_ai = tmp_path / "without_ai.html"
    page_with_ai = tmp_path / "with_ai.html"

    dashboard.generate_html([_job()], page_without_ai)
    dashboard.generate_html([_job(ai_suitable=True, ai_reason="ok")], page_with_ai)

    assert "good matches" not in page_without_ai.read_text(encoding="utf-8")
    assert 'id="chip-ai"' not in page_without_ai.read_text(encoding="utf-8")
    assert 'id="chip-ai"' in page_with_ai.read_text(encoding="utf-8")


def _page(dashboard, tmp_path: Path, jobs: list[dict]) -> str:
    output_path = tmp_path / "index.html"
    dashboard.generate_html(jobs, output_path)
    return output_path.read_text(encoding="utf-8")


def test_card_shows_country_source_dates_and_status(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(status="active", last_verified="2026-11-08T10:00:00", first_seen="2026-11-01T09:00:00"))

    assert "Chiasso, Switzerland" in card
    assert "jobs.ch" in card
    assert "2026-06-10" in card
    assert "2026-11-08" in card
    assert "Seen in the latest scan" in card
    assert 'data-country="CH"' in card


def test_missing_dates_are_not_invented(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(date="3 days ago"))

    assert "Not stated" in card
    assert "Before tracking" in card


def test_imprecise_location_is_flagged_and_has_no_distance(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(city="Lombardia", source="indeed.it"))

    assert "location not precise" in card
    assert 'data-precise="no"' in card
    assert 'class="route"' not in card


def test_cached_and_expired_jobs_are_not_presented_as_fresh(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    cached = dashboard.build_card(_job(status="cached_source_unavailable", status_reason="jobs.ch was not scanned"))
    expired = dashboard.build_card(_job(status="possibly_expired"))

    assert "Not re-checked" in cached
    assert "jobs.ch was not scanned" in cached
    assert "Possibly expired" in expired
    assert 'class="card old"' in expired
    assert "Seen in the latest scan" not in cached + expired


def test_stated_salary_is_shown_with_origin_and_assumptions(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    card = dashboard.build_card(_job(city="Monza MB", source="indeed.it", description="Offriamo RAL 28.000 - 30.000"))

    assert "Read from the listing text" in card
    assert "28,000&ndash;30,000 EUR / year, gross" in card
    assert "Net estimate" in card
    assert "How this is estimated" in card
    assert "Indicative estimate" in card


def test_ai_salary_estimate_is_labelled_and_missing_salary_says_so(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    estimated = dashboard.build_card(_job(ai_salary={"amount": 4200, "currency": "CHF", "period": "month"}))
    missing = dashboard.build_card(_job())

    assert "AI estimate" in estimated
    assert "Swiss social contributions" in estimated
    assert "Not available" in missing
    assert 'data-salary="unavailable"' in missing


def test_other_portals_are_linked_and_escaped(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    job = _job(sources=[
        {"source": "jobs.ch", "url": "https://www.jobs.ch/it/annuncio/123"},
        {"source": "indeed.ch", "url": "https://ch.indeed.com/viewjob?jk=1"},
        {"source": "x<script>", "url": "javascript:alert(1)"},
    ])
    card = dashboard.build_card(job)

    assert "Also on" in card
    assert "ch.indeed.com/viewjob" in card
    assert "javascript:alert" not in card
    assert "<script>" not in card


def test_filters_cover_country_seniority_freshness_salary_place_and_source(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    jobs = [
        _job(status="active", title="Junior Python developer"),
        _job(city="Monza MB", source="indeed.it", url="https://it.indeed.com/1", status="possibly_expired",
             title="Senior Java engineer", description="RAL 40.000"),
    ]
    page = _page(dashboard, tmp_path, jobs)

    for expected in ("Country", "Seniority", "Freshness", "Salary", 'id="place"', 'id="source"', 'id="precise"',
                     "Italy", "Switzerland", "Possibly expired", "Monza"):
        assert expected in page
    assert 'data-filter="country"' in page


def test_exchange_rate_is_named_when_a_swiss_job_is_shown(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    rate = dashboard.FxRate(1.0937, "ECB reference rate", "2026-11-06")
    output_path = tmp_path / "index.html"

    dashboard.generate_html([_job()], output_path, fx_rate=rate)
    page = output_path.read_text(encoding="utf-8")

    assert "1.0937 EUR (ECB reference rate of 2026-11-06)" in page


def test_page_with_only_italian_jobs_does_not_mention_francs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    page = _page(dashboard, tmp_path, [_job(city="Monza MB", source="indeed.it", url="https://it.indeed.com/1")])

    assert "CHF converted" not in page
    assert "Lombardy" in page


def test_newest_published_listing_comes_first(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    older = _job(title="Older job", date="2026-05-01", url="https://x.ch/1")
    newer = _job(title="Newer job", date="2026-06-20", url="https://x.ch/2")
    page = _page(dashboard, tmp_path, [older, newer])

    assert page.index("Newer job") < page.index("Older job")


ENGLISH_TEXT = (
    "We are looking for a developer with experience in the cloud, and you will work with our team on the platform. "
    "You will build services for our customers and the team."
)
ITALIAN_TEXT = (
    "Cerchiamo una persona con esperienza nello sviluppo di applicazioni per la nostra azienda, che lavori con il team "
    "e con i clienti."
)


def test_an_english_description_gets_a_translate_to_italian_button(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(description=ENGLISH_TEXT))

    assert 'data-lang="en"' in card
    assert 'data-action="translate" data-from="en"' in card
    assert "Translate to Italian" in card


def test_an_italian_description_needs_no_translate_button(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(description=ITALIAN_TEXT))

    assert 'data-lang="it"' in card
    assert "Translate to Italian" not in card


def test_a_card_without_listing_text_has_no_description_block(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(description=""))

    assert 'class="desc"' not in card
    assert "Translate to Italian" not in card


def test_a_login_wall_stored_by_an_older_scan_is_not_shown(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    wall = " | ".join(["Iscriviti o accedi per trovare il tuo prossimo lavoro", "Email o telefono", "Password",
                       "Hai dimenticato la password? Accedi", "Non hai un account LinkedIn? Iscriviti ora"])

    card = dashboard.build_card(_job(source="linkedin.it", description=wall))

    assert "Hai dimenticato la password" not in card
    assert 'class="desc"' not in card


def test_a_long_description_is_shortened_until_opened_and_every_paragraph_is_escaped(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    long_text = " | ".join([
        ENGLISH_TEXT,
        "<script>alert(1)</script> and more text for the second paragraph.",
        ENGLISH_TEXT.replace("developer", "tester"),
        ENGLISH_TEXT.replace("developer", "designer"),
    ])

    card = dashboard.build_card(_job(description=long_text))

    assert 'class="desc-text clamp"' in card
    assert 'data-action="expand"' in card
    assert "<script>alert" not in card
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in card


def test_a_short_description_is_shown_whole_without_an_expand_button(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(description="Posizione 100% remoto."))

    assert 'class="desc-text"' in card
    assert 'data-action="expand"' not in card


def test_the_page_script_has_no_ternary_and_the_translate_code_is_in_the_hash_protected_script(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output = tmp_path / "index.html"

    dashboard.generate_html([_job(description=ENGLISH_TEXT)], output)
    page = output.read_text(encoding="utf-8")

    assert "async function onTranslateClick" in page
    assert "translate.google.com" in page
    assert dashboard._script_hash(page[page.index("<script>") + len("<script>"):page.index("</script>")]) in page


def test_the_search_text_is_escaped_exactly_once(monkeypatch: MonkeyPatch) -> None:
    """Twice-escaped text ("at&amp;amp;t") is still safe markup, but the search cannot find "AT&T"."""
    job = {"title": "<b>Network</b> Engineer", "company": "AT&T \"Ticino\" & O'Brien", "city": "Chiasso",
           "url": "https://www.jobs.ch/it/annuncio/1", "source": "jobs.ch"}

    card = load_dashboard_module(monkeypatch).build_card(job)

    assert 'data-search="&lt;b&gt;network&lt;/b&gt; engineer at&amp;t &quot;ticino&quot; &amp; o&#x27;brien chiasso' in card
    assert "&amp;amp;" not in card
    assert "&amp;lt;" not in card
    assert "<b>Network</b>" not in card
