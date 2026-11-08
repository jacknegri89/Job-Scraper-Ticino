"""Tests for configurable home-to-place distance calculations."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).parent.parent))

import geo


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
    chiasso = geo.find_place("Chiasso").place
    distance = load_distance_module(monkeypatch, home_lat=chiasso.lat, home_lng=chiasso.lng)

    assert distance.km_from_home("Chiasso") == 0.0
    assert distance.km_from_home("Mendrisio") > 0


def test_distance_works_for_lombardy_and_ticino(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    milan_km = distance.km_from_home("Milano MI")
    chiasso_km = distance.km_from_home("Chiasso")
    assert 45 <= milan_km <= 60
    assert 90 <= chiasso_km <= 95


def test_accepts_portal_place_variants(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("6850 Mendrisio") == distance.km_from_home("Mendrisio")
    assert distance.km_from_home("Stabio, TI") == distance.km_from_home("Stabio")
    assert distance.km_from_home("Balerna TI") == distance.km_from_home("Balerna")


def test_generic_unknown_and_empty_locations_have_no_distance(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("Lombardia") is None
    assert distance.km_from_home("Provincia di Varese") is None
    assert distance.km_from_home("Cittanonesistente") is None
    assert distance.km_from_home("") is None
    assert distance.km_from_home(None) is None


def test_ambiguous_place_name_has_no_distance(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_from_home("Bodio") is None
    assert distance.km_from_home("Bodio TI") is not None


def test_existing_dashboard_api_matches_english_api(monkeypatch: MonkeyPatch) -> None:
    distance = load_distance_module(monkeypatch)

    assert distance.km_da_casa("Chiasso") == distance.km_from_home("Chiasso")


def test_without_personal_config_distances_are_disabled(monkeypatch: MonkeyPatch) -> None:
    # A None entry makes "from user_config import ..." fail as if the file did not exist.
    monkeypatch.setitem(sys.modules, "user_config", None)
    distance = importlib.reload(importlib.import_module("distance_calculator"))

    assert distance.is_home_configured() is False
    assert distance.km_from_home("Chiasso") is None
