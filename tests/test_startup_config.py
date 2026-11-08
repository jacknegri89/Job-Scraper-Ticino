"""Test della configurazione iniziale e delle scelte applicate alla ricerca."""

import argparse
import json

import pytest

import ai_analyzer
import dashboard_builder
import distance_calculator
import job_filter
import main
import startup_config


CITIES = {"chiasso", "mendrisio"}
SOURCES = {"jobs.ch", "indeed.ch"}


def test_configuration_saves_custom_choices(tmp_path):
    settings = startup_config.default_settings(CITIES, sorted(SOURCES), ["operaio"])
    settings.update(cities=["chiasso"], sources=["jobs.ch"], search_terms=["tecnico", "help desk"],
                    home_city="Como", home_lat=45.81, home_lng=9.08,
                    ai_enabled=True, candidate_profile="Tecnico IT", headless=True)
    path = tmp_path / "settings.json"
    startup_config.validate_settings(settings, CITIES, SOURCES)
    startup_config.save_settings(path, settings)
    loaded = startup_config.load_settings(path, CITIES, SOURCES)

    assert loaded["cities"] == ["chiasso"]
    assert loaded["sources"] == ["jobs.ch"]
    assert loaded["search_terms"] == ["tecnico", "help desk"]
    assert (loaded["home_lat"], loaded["home_lng"]) == (45.81, 9.08)
    assert loaded["candidate_profile"] == "Tecnico IT"
    assert loaded["ai_enabled"] and loaded["headless"]


@pytest.mark.parametrize("field,value", [
    ("cities", ["non riconosciuta"]),
    ("sources", ["https://example.com"]),
    ("search_terms", []),
    ("home_lat", 91),
    ("ai_enabled", "true"),
])
def test_invalid_saved_settings_are_rejected(field, value):
    settings = startup_config.default_settings(CITIES, sorted(SOURCES), ["operaio"])
    settings[field] = value
    with pytest.raises(ValueError):
        startup_config.validate_settings(settings, CITIES, SOURCES)


def test_apply_settings_changes_search_and_disables_distance(monkeypatch):
    settings = startup_config.default_settings(CITIES, sorted(SOURCES), ["tecnico"])
    settings.update(cities=["chiasso"], sources=["jobs.ch"], headless=True)
    monkeypatch.setattr(job_filter, "ALLOWED_CITIES", set(job_filter.ALLOWED_CITIES))
    monkeypatch.setattr(job_filter, "SEARCH_TERMS", list(job_filter.SEARCH_TERMS))
    monkeypatch.setattr(distance_calculator, "_HOME_COORDINATES", (45.0, 9.0))
    monkeypatch.setattr(dashboard_builder, "HOME_CITY", "Home")
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", None)
    monkeypatch.setattr(main, "_AI_ENABLED", True)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main.config, "HEADLESS", False)
    monkeypatch.setattr(main.config, "PAGE_TIMEOUT_MS", 30000)
    monkeypatch.setattr(main.config, "MAX_ATTEMPTS", 2)
    args = argparse.Namespace(only="", timeout=0)

    main._apply_search_settings(settings, args)

    assert job_filter.ALLOWED_CITIES == {"chiasso"}
    assert job_filter.SEARCH_TERMS == ["tecnico"]
    assert distance_calculator.km_from_home("chiasso") is None
    assert args.only == "jobs.ch"
    assert main.config.HEADLESS is True
    assert main._AI_ENABLED is False


def test_cli_only_overrides_sources_for_scan(monkeypatch):
    settings = startup_config.default_settings(CITIES, sorted(SOURCES), ["operaio"])
    monkeypatch.setattr(job_filter, "ALLOWED_CITIES", set(job_filter.ALLOWED_CITIES))
    monkeypatch.setattr(job_filter, "SEARCH_TERMS", list(job_filter.SEARCH_TERMS))
    monkeypatch.setattr(distance_calculator, "_HOME_COORDINATES", (45.0, 9.0))
    monkeypatch.setattr(dashboard_builder, "HOME_CITY", "Home")
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", None)
    monkeypatch.setattr(main, "_AI_ENABLED", True)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main.config, "PAGE_TIMEOUT_MS", 30000)
    monkeypatch.setattr(main.config, "MAX_ATTEMPTS", 2)
    args = argparse.Namespace(only="indeed.ch", timeout=0)
    main._apply_search_settings(settings, args)
    assert args.only == "indeed.ch"


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        startup_config.load_settings(path, CITIES, SOURCES)
    assert path.read_text(encoding="utf-8") == "{"


