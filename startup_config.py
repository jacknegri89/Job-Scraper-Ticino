"""Saved search settings: defaults, validation and atomic saving."""

import json
import math
import os
import tempfile
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / "user_settings.json"
MAX_TEXT_LENGTH = 3000
MAX_ITEMS = 100


def default_settings(cities, sources, search_terms):
    return {
        "cities": sorted(cities),
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
    }


def load_settings(path, allowed_cities, allowed_sources):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    validate_settings(settings, allowed_cities, allowed_sources)
    return settings


def validate_settings(settings, allowed_cities, allowed_sources):
    if not isinstance(settings, dict):
        raise ValueError("The settings must be a JSON object.")
    required_keys = {"cities", "sources", "search_terms", "home_city", "home_lat", "home_lng",
                     "ai_enabled", "candidate_profile", "headless", "timeout_ms", "attempts"}
    if set(settings) != required_keys:
        raise ValueError("The settings contain missing or unknown fields.")
    for key, allowed in (("cities", allowed_cities), ("sources", allowed_sources)):
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
    for key in ("home_city", "candidate_profile"):
        if not isinstance(settings.get(key), str) or len(settings[key]) > MAX_TEXT_LENGTH:
            raise ValueError(f"The {key} field is not valid.")
    for key in ("ai_enabled", "headless"):
        if not isinstance(settings.get(key), bool):
            raise ValueError(f"The {key} field must be true or false.")
    for key, minimum, maximum in (("timeout_ms", 1000, 120000), ("attempts", 1, 3)):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"The {key} value must be between {minimum} and {maximum}.")
    _validate_coordinates(settings)


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


