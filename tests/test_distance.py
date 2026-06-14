"""Tests for configurable home-to-city distance calculations."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_distance_module(
    monkeypatch: MonkeyPatch,
    *,
    home_lat: float = 45.0,
    home_lng: float = 9.0,
    home_city: str = "Home",
) -> ModuleType:
    config = ModuleType("user_config")
    config.HOME_LAT = home_lat
    config.HOME_LNG = home_lng
    config.HOME_CITY = home_city
    monkeypatch.setitem(sys.modules, "user_config", config)

    if "distance_calculator" in sys.modules:
        return importlib.reload(sys.modules["distance_calculator"])

    return importlib.import_module("distance_calculator")


def test_distance_uses_configured_home_coordinates(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(
        monkeypatch,
        home_lat=45.8320,
        home_lng=9.0310,
    )

    assert distance.km_from_home("Chiasso") == 0.0
    assert distance.km_from_home("Mendrisio") > 0


def test_chiasso_distance_from_neutral_home_is_plausible(
    monkeypatch: MonkeyPatch,
) -> None:
    distance = load_distance_module(monkeypatch)

    km = distance.km_from_home("Chiasso")

    assert km is not None
    assert 92 <= km <= 93


def test_riva_san_vitale_is_farther_than_chiasso(
    monkeypatch: MonkeyPatch,
) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("Riva San Vitale") > distance.km_from_home("Chiasso")


def test_accepts_portal_city_variants(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("6850 Mendrisio") == distance.km_from_home("Mendrisio")
    assert distance.km_from_home("Stabio, TI") == distance.km_from_home("Stabio")
    assert distance.km_from_home("Balerna TI") == distance.km_from_home("Balerna")


def test_unknown_city_returns_none(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("Zurich") is None
    assert distance.km_from_home("") is None
    assert distance.km_from_home(None) is None


def test_all_allowed_cities_have_coordinates(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    from job_filter import ALLOWED_CITIES

    missing_cities = [
        city for city in ALLOWED_CITIES if distance.km_from_home(city) is None
    ]
    assert missing_cities == []


def test_existing_dashboard_api_matches_english_api(
    monkeypatch: MonkeyPatch,
) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_da_casa("Chiasso") == distance.km_from_home("Chiasso")
