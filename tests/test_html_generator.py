"""Smoke tests for the dashboard generator."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_dashboard_module(monkeypatch: MonkeyPatch) -> ModuleType:
    config = ModuleType("user_config")
    config.HOME_LAT = 45.8320
    config.HOME_LNG = 9.0310
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

    card = dashboard.build_card(_job(city="Lugano"))

    assert 'data-km="9999"' in card
    assert "<span class=\"meta-v\">-</span>" in card


def test_card_escapes_html_fields(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(title='<script>alert("x")</script>'))

    assert "<script>alert" not in card
    assert "&lt;script&gt;" in card


def test_card_rejects_non_http_url(monkeypatch: MonkeyPatch) -> None:
    dashboard = load_dashboard_module(monkeypatch)

    card = dashboard.build_card(_job(url="javascript:alert(1)"))

    assert 'href="#"' in card
    assert "javascript:alert" not in card


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


def test_generate_html_with_no_jobs_shows_empty_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dashboard = load_dashboard_module(monkeypatch)
    output_path = tmp_path / "empty.html"

    dashboard.generate_html([], output_path)
    page = output_path.read_text(encoding="utf-8")

    assert 'class="empty show"' in page
