"""Tests for saved settings, their migration and how they are applied to a search."""

import argparse
import json

import pytest

import ai_analyzer
import dashboard_builder
import distance_calculator
import job_filter
import main
import startup_config

SOURCES = {"jobs.ch", "indeed.ch", "indeed.it"}

LEGACY_SETTINGS = {
    "cities": ["chiasso", "mendrisio"],
    "sources": ["jobs.ch"],
    "search_terms": ["operaio"],
    "home_city": "Como",
    "home_lat": 45.81,
    "home_lng": 9.08,
    "ai_enabled": True,
    "candidate_profile": "Tecnico IT",
    "headless": True,
    "timeout_ms": 30000,
    "attempts": 2,
}


def _settings(**changes):
    settings = startup_config.default_settings(sorted(SOURCES), ["operaio"])
    settings.update(changes)
    return settings


def test_configuration_saves_custom_choices(tmp_path):
    settings = _settings(regions=["LOM"], radius_km=25, include_places=["BS", "Lugano"], sources=["indeed.it"],
                         search_terms=["tecnico", "help desk"], home_city="Como", home_lat=45.81, home_lng=9.08,
                         ai_enabled=True, candidate_profile="Tecnico IT", categories=["tech"],
                         seniority_levels=["junior", "unknown"], contract_types=["permanent", "unknown"],
                         include_uncertain_location=True, expiry_days=10, retention_days=30)
    path = tmp_path / "settings.json"
    startup_config.validate_settings(settings, SOURCES)
    startup_config.save_settings(path, settings)
    loaded = startup_config.load_settings(path, SOURCES)

    assert loaded == settings


@pytest.mark.parametrize("field,value", [
    ("regions", ["XX"]),
    ("regions", []),
    ("sources", ["https://example.com"]),
    ("search_terms", []),
    ("categories", ["nonsense"]),
    ("seniority_levels", ["wizard"]),
    ("contract_types", []),
    ("radius_km", 0),
    ("radius_km", 100000),
    ("radius_km", True),
    ("include_places", ["x" * 100]),
    ("include_uncertain_location", "yes"),
    ("home_lat", 91),
    ("ai_enabled", "true"),
    ("expiry_days", 0),
    ("expiry_days", 400),
    ("fx_mode", "bank"),
    ("fx_manual_eur_per_chf", 50),
    ("schema_version", 3),
])
def test_invalid_saved_settings_are_rejected(field, value):
    settings = _settings(home_lng=9.0)
    settings[field] = value
    with pytest.raises(ValueError):
        startup_config.validate_settings(settings, SOURCES)


def test_retention_must_not_be_shorter_than_expiry():
    with pytest.raises(ValueError):
        startup_config.validate_settings(_settings(expiry_days=30, retention_days=10), SOURCES)


def test_manual_exchange_rate_mode_needs_a_rate():
    with pytest.raises(ValueError):
        startup_config.validate_settings(_settings(fx_mode="manual"), SOURCES)
    startup_config.validate_settings(_settings(fx_mode="manual", fx_manual_eur_per_chf=1.08), SOURCES)


def test_unknown_or_missing_fields_are_rejected():
    settings = _settings()
    settings["surprise"] = 1
    with pytest.raises(ValueError):
        startup_config.validate_settings(settings, SOURCES)
    del settings["surprise"], settings["regions"]
    with pytest.raises(ValueError):
        startup_config.validate_settings(settings, SOURCES)


def test_previous_settings_are_migrated_keeping_their_meaning_and_a_backup_is_made(tmp_path):
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps(LEGACY_SETTINGS), encoding="utf-8")

    migrated = startup_config.load_settings(path, SOURCES)

    assert migrated["schema_version"] == 2
    assert migrated["regions"] == ["TI"]
    assert migrated["radius_km"] is None
    assert migrated["include_places"] == ["chiasso", "mendrisio"]
    assert (migrated["home_lat"], migrated["home_lng"], migrated["candidate_profile"]) == (45.81, 9.08, "Tecnico IT")
    assert json.loads((tmp_path / "user_settings.json.v1.bak").read_text(encoding="utf-8")) == LEGACY_SETTINGS
    assert json.loads(path.read_text(encoding="utf-8")) == migrated


def test_migration_backup_is_never_overwritten(tmp_path):
    path = tmp_path / "user_settings.json"
    backup = tmp_path / "user_settings.json.v1.bak"
    backup.write_text("original backup", encoding="utf-8")
    path.write_text(json.dumps(LEGACY_SETTINGS), encoding="utf-8")

    startup_config.load_settings(path, SOURCES)

    assert backup.read_text(encoding="utf-8") == "original backup"


def test_unknown_settings_format_is_left_untouched(tmp_path):
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps({"something": "else"}), encoding="utf-8")

    with pytest.raises(ValueError):
        startup_config.load_settings(path, SOURCES)

    assert json.loads(path.read_text(encoding="utf-8")) == {"something": "else"}
    assert not (tmp_path / "user_settings.json.v1.bak").exists()


def _isolate_main(monkeypatch):
    monkeypatch.setattr(job_filter, "SEARCH_TERMS", list(job_filter.SEARCH_TERMS))
    monkeypatch.setattr(distance_calculator, "_HOME_COORDINATES", (45.0, 9.0))
    monkeypatch.setattr(dashboard_builder, "HOME_CITY", "Home")
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", None)
    monkeypatch.setattr(main, "_AI_ENABLED", True)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main, "_PREFERENCES", main.SearchPreferences())
    monkeypatch.setattr(main.config, "HEADLESS", False)
    monkeypatch.setattr(main.config, "PAGE_TIMEOUT_MS", 30000)
    monkeypatch.setattr(main.config, "MAX_ATTEMPTS", 2)


def test_apply_settings_changes_search_and_disables_distance(monkeypatch):
    _isolate_main(monkeypatch)
    settings = _settings(sources=["jobs.ch"], search_terms=["tecnico"], regions=["TI"], radius_km=None,
                         include_places=["Chiasso"], categories=["tech"], seniority_levels=["junior"],
                         fx_mode="manual", fx_manual_eur_per_chf=1.07)
    args = argparse.Namespace(only="", timeout=0)

    main._apply_search_settings(settings, args)

    assert job_filter.SEARCH_TERMS == ["tecnico"]
    assert distance_calculator.km_from_home("chiasso") is None
    assert args.only == "jobs.ch"
    assert main.config.HEADLESS is True
    assert main._AI_ENABLED is False
    preferences = main._PREFERENCES
    assert preferences.area.regions == frozenset({"TI"})
    assert "chiasso" in preferences.area.include_places
    assert preferences.categories == frozenset({"tech"})
    assert preferences.seniority_levels == frozenset({"junior"})
    assert main._current_fx_rate().eur_per_chf == 1.07


def test_radius_and_home_become_the_search_area(monkeypatch):
    _isolate_main(monkeypatch)
    settings = _settings(home_city="Seveso", home_lat=45.65, home_lng=9.13, radius_km=30)

    main._apply_search_settings(settings, argparse.Namespace(only="", timeout=0))

    assert main._PREFERENCES.area.radius_km == 30
    assert main._PREFERENCES.area.home == (45.65, 9.13)
    assert distance_calculator.km_from_home("Milano") is not None


def test_radius_without_a_starting_point_is_reported(monkeypatch, capsys):
    _isolate_main(monkeypatch)
    main._apply_search_settings(_settings(radius_km=30), argparse.Namespace(only="", timeout=0))

    assert "limit is ignored" in capsys.readouterr().out


def test_cli_only_overrides_sources_for_scan(monkeypatch):
    _isolate_main(monkeypatch)
    args = argparse.Namespace(only="indeed.ch", timeout=0)
    main._apply_search_settings(_settings(), args)
    assert args.only == "indeed.ch"


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        startup_config.load_settings(path, SOURCES)
    assert path.read_text(encoding="utf-8") == "{"
