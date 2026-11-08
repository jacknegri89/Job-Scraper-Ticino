"""Saved search settings: defaults, validation, migration and atomic saving."""

import json
import math
import os
import shutil
import tempfile
from pathlib import Path

from fx_rates import FX_MODE_ECB, FX_MODE_MANUAL, MAX_PLAUSIBLE_EUR_PER_CHF, MIN_PLAUSIBLE_EUR_PER_CHF
from geo import ALL_REGIONS, REGION_TICINO
from job_classifier import CONTRACT_TYPES, SENIORITY_LEVELS
from job_filter import ALL_CATEGORIES
from preferences import (
    DEFAULT_EXPIRY_DAYS,
    DEFAULT_RADIUS_KM,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_VERIFY_LIMIT,
    MAX_DAYS,
    MAX_RADIUS_KM,
)

SETTINGS_FILE = Path(__file__).resolve().parent / "user_settings.json"
SETTINGS_SCHEMA_VERSION = 2
LEGACY_BACKUP_SUFFIX = ".v1.bak"
MAX_TEXT_LENGTH = 3000
MAX_ITEMS = 100
MAX_PLACE_LENGTH = 60

_LEGACY_KEYS = {"cities", "sources", "search_terms", "home_city", "home_lat", "home_lng",
                "ai_enabled", "candidate_profile", "headless", "timeout_ms", "attempts"}
_CURRENT_KEYS = _LEGACY_KEYS - {"cities"} | {
    "schema_version", "regions", "radius_km", "include_places", "include_uncertain_location", "include_remote",
    "categories", "seniority_levels", "contract_types", "expiry_days", "retention_days",
    "verify_limit", "fx_mode", "fx_manual_eur_per_chf",
}


def default_settings(sources, search_terms):
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "regions": list(ALL_REGIONS),
        "radius_km": DEFAULT_RADIUS_KM,
        "include_places": [],
        "include_uncertain_location": False,
        "include_remote": False,
        "categories": list(ALL_CATEGORIES),
        "seniority_levels": list(SENIORITY_LEVELS),
        "contract_types": list(CONTRACT_TYPES),
        "sources": list(sources),
        "search_terms": list(search_terms),
        "home_city": "",
        "home_lat": None,
        "home_lng": None,
        "ai_enabled": False,
        "candidate_profile": "",
        "headless": True,
        "timeout_ms": 30000,
        "attempts": 2,
        "expiry_days": DEFAULT_EXPIRY_DAYS,
        "retention_days": DEFAULT_RETENTION_DAYS,
        "verify_limit": DEFAULT_VERIFY_LIMIT,
        "fx_mode": FX_MODE_ECB,
        "fx_manual_eur_per_chf": None,
    }


def migrate_legacy_settings(legacy):
    """Turn a version 1 settings file (a list of Ticino municipalities) into version 2.

    The old behaviour is kept: only the listed municipalities, in Ticino, no radius.
    """
    if set(legacy) != _LEGACY_KEYS:
        raise ValueError("The settings file has an unknown format; it was not changed.")
    migrated = default_settings(legacy["sources"], legacy["search_terms"])
    for key in _LEGACY_KEYS - {"cities", "sources", "search_terms"}:
        migrated[key] = legacy[key]
    migrated["regions"] = [REGION_TICINO]
    migrated["radius_km"] = None
    migrated["include_places"] = sorted(str(city) for city in legacy["cities"])
    return migrated


def load_settings(path, allowed_sources):
    """Read, migrate (with a one-time backup) and validate the saved settings."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    if isinstance(settings, dict) and settings.get("schema_version") is None:
        settings = _migrate_and_save(path, settings)
    validate_settings(settings, allowed_sources)
    return settings


def _migrate_and_save(path, legacy_settings):
    migrated = migrate_legacy_settings(legacy_settings)
    backup_path = path.with_name(path.name + LEGACY_BACKUP_SUFFIX)
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
    save_settings(path, migrated)
    return migrated


def validate_settings(settings, allowed_sources):
    if not isinstance(settings, dict):
        raise ValueError("The settings must be a JSON object.")
    if set(settings) != _CURRENT_KEYS:
        raise ValueError("The settings contain missing or unknown fields.")
    if settings["schema_version"] != SETTINGS_SCHEMA_VERSION:
        raise ValueError("The settings were saved by a newer version of JobScraper.")
    _validate_choice_lists(settings, allowed_sources)
    _validate_text_fields(settings)
    _validate_numbers(settings)
    _validate_places(settings)
    _validate_fx(settings)
    _validate_coordinates(settings)


def _validate_choice_lists(settings, allowed_sources):
    choices = (
        ("regions", ALL_REGIONS), ("sources", allowed_sources), ("categories", ALL_CATEGORIES),
        ("seniority_levels", SENIORITY_LEVELS), ("contract_types", CONTRACT_TYPES),
    )
    for key, allowed in choices:
        values = settings.get(key)
        if not isinstance(values, list) or not values or len(values) > MAX_ITEMS:
            raise ValueError(f"The {key} list must contain at least one valid choice.")
        if any(not isinstance(value, str) or value not in allowed for value in values):
            raise ValueError(f"The {key} list contains unknown values.")
    terms = settings.get("search_terms")
    if not isinstance(terms, list) or not terms or len(terms) > MAX_ITEMS:
        raise ValueError("Enter at least one valid search term.")
    if any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms):
        raise ValueError("Each search term must be 1 to 100 characters long.")


def _validate_text_fields(settings):
    for key in ("home_city", "candidate_profile"):
        if not isinstance(settings.get(key), str) or len(settings[key]) > MAX_TEXT_LENGTH:
            raise ValueError(f"The {key} field is not valid.")
    for key in ("ai_enabled", "headless", "include_uncertain_location", "include_remote"):
        if not isinstance(settings.get(key), bool):
            raise ValueError(f"The {key} field must be true or false.")


def _validate_numbers(settings):
    for key, minimum, maximum in (
        ("timeout_ms", 1000, 120000), ("attempts", 1, 3),
        ("expiry_days", 1, MAX_DAYS), ("retention_days", 1, MAX_DAYS), ("verify_limit", 0, 100),
    ):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"The {key} value must be between {minimum} and {maximum}.")
    if settings["retention_days"] < settings["expiry_days"]:
        raise ValueError("Keep old listings at least as long as the expiry period.")
    radius = settings.get("radius_km")
    if radius is None:
        return
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 0 < radius <= MAX_RADIUS_KM:
        raise ValueError(f"The radius must be between 1 and {MAX_RADIUS_KM} km, or empty.")


def _validate_places(settings):
    places = settings.get("include_places")
    if not isinstance(places, list) or len(places) > MAX_ITEMS:
        raise ValueError("The list of extra places is not valid.")
    for place in places:
        if not isinstance(place, str) or not place.strip() or len(place) > MAX_PLACE_LENGTH:
            raise ValueError("Each extra place must be 1 to 60 characters long.")


def _validate_fx(settings):
    if settings.get("fx_mode") not in (FX_MODE_ECB, FX_MODE_MANUAL):
        raise ValueError("The exchange rate mode must be 'ecb' or 'manual'.")
    rate = settings.get("fx_manual_eur_per_chf")
    if rate is None:
        if settings["fx_mode"] == FX_MODE_MANUAL:
            raise ValueError("Enter the exchange rate to use in manual mode.")
        return
    valid = (
        not isinstance(rate, bool)
        and isinstance(rate, (int, float))
        and MIN_PLAUSIBLE_EUR_PER_CHF <= rate <= MAX_PLAUSIBLE_EUR_PER_CHF
    )
    if not valid:
        raise ValueError("The exchange rate is not a plausible EUR per CHF value.")


def _validate_coordinates(settings):
    latitude = settings.get("home_lat")
    longitude = settings.get("home_lng")
    if latitude is None and longitude is None:
        return
    for value, limit in ((latitude, 90), (longitude, 180)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Enter both coordinates or neither.")
        try:
            valid = math.isfinite(value) and -limit <= value <= limit
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("The coordinates are not valid.")


def save_settings(path, settings):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings-", suffix=".tmp", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(settings, temporary_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
