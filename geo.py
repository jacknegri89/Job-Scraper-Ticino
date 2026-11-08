"""Places in Lombardy and Ticino: lookup, location certainty and the search area.

A job location is resolved to one of four certainty levels. A distance is only
computed for exact places, never for generic text such as "Lombardia".
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "places.json"

REGION_LOMBARDY = "LOM"
REGION_TICINO = "TI"
ALL_REGIONS = (REGION_LOMBARDY, REGION_TICINO)

CERTAINTY_EXACT = "exact"
CERTAINTY_AMBIGUOUS = "ambiguous"
CERTAINTY_REGION_ONLY = "region_only"
CERTAINTY_UNKNOWN = "unknown"

AREA_IN = "in_area"
AREA_OUT = "out_of_area"
AREA_UNCERTAIN = "uncertain"

EARTH_RADIUS_KM = 6371.0

_REGION_WORDS = {
    "lombardia": REGION_LOMBARDY,
    "lombardy": REGION_LOMBARDY,
    "ticino": REGION_TICINO,
}
_COUNTRY_WORDS = {"italia", "italy", "svizzera", "schweiz", "switzerland", "suisse", "ch", "it"}
_VAGUE_MARKERS = ("hinterland", "dintorni", "provincia", "province", "remot", "smart working", "tutta", "varie", "diverse")
_POSTAL_CODE = re.compile(r"\b\d{4,5}\b")
# Portals write "Remoto in Lomazzo" or "Ibrido a Milano": the place is what follows.
_WORK_MODE_PREFIX = re.compile(
    r"^(?:remoto|remote|ibrido|hybrid|home\s?working|smart\s?working|telelavoro)\s+(?:in|a|presso|da|-)\s+",
    re.IGNORECASE)
_REMOTE_WORDS = re.compile(r"\b(?:remoto|remote|da casa|home\s?working|smart\s?working|telelavoro)\b", re.IGNORECASE)
_HYBRID_WORDS = re.compile(r"\b(?:ibrido|hybrid)\b", re.IGNORECASE)
WORK_MODE_REMOTE = "remote"
WORK_MODE_HYBRID = "hybrid"
WORK_MODE_ONSITE = ""
_PROVINCE_SUFFIX = re.compile(r"[\s,(/-]+\(?([A-Za-z]{2})\)?\s*$")


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    region: str
    province: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Location:
    """Result of resolving a free-text job location."""

    certainty: str
    place: Place | None = None
    region: str = ""
    candidates: tuple[Place, ...] = ()


@dataclass(frozen=True)
class AreaPolicy:
    """Which regions, which radius and which extra places the user wants."""

    regions: frozenset[str] = frozenset(ALL_REGIONS)
    radius_km: float | None = None
    home: tuple[float, float] | None = None
    include_places: frozenset[str] = frozenset()


def fold_text(text: str) -> str:
    """Lowercase, remove accents and collapse spaces: 'Cantù ' -> 'cantu'."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents.lower().replace("'", " ").replace("’", " ")).strip()


@lru_cache(maxsize=1)
def load_places() -> tuple[Place, ...]:
    document = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return tuple(Place(*row) for row in document["places"])


@lru_cache(maxsize=1)
def _places_by_name() -> dict[str, tuple[Place, ...]]:
    index: dict[str, list[Place]] = {}
    for place in load_places():
        index.setdefault(fold_text(place.name), []).append(place)
    return {name: tuple(places) for name, places in index.items()}


@lru_cache(maxsize=1)
def _province_codes() -> frozenset[str]:
    return frozenset(place.province for place in load_places() if place.country == "IT")


def haversine_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    origin_lat, origin_lng = map(radians, origin)
    destination_lat, destination_lng = map(radians, destination)
    delta_lat = destination_lat - origin_lat
    delta_lng = destination_lng - origin_lng
    half_chord = sin(delta_lat / 2) ** 2 + cos(origin_lat) * cos(destination_lat) * sin(delta_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(half_chord))


def find_place(name: str, province: str = "", country: str = "") -> Location:
    """Look a place up by name; use a province or country hint to break ties."""
    candidates = list(_places_by_name().get(fold_text(name), ()))
    if not candidates:
        return Location(CERTAINTY_UNKNOWN)
    narrowed = _narrow_candidates(candidates, province, country)
    if len(narrowed) == 1:
        return Location(CERTAINTY_EXACT, place=narrowed[0], region=narrowed[0].region)
    return Location(CERTAINTY_AMBIGUOUS, candidates=tuple(narrowed))


def _narrow_candidates(candidates: list[Place], province: str, country: str) -> list[Place]:
    if province:
        by_province = [place for place in candidates if place.province == province.upper()]
        if by_province:
            return by_province
    if country:
        by_country = [place for place in candidates if place.country == country]
        if by_country:
            return by_country
    return candidates


def resolve_location(raw_location: str | None, country_hint: str = "") -> Location:
    """Turn text such as 'Monza MB', '6830 Chiasso' or 'Lombardia' into a Location."""
    text = _WORK_MODE_PREFIX.sub("", (raw_location or "").strip())
    if not text:
        return Location(CERTAINTY_UNKNOWN)
    parts = [part.strip() for part in re.split(r"[,|]", text) if part.strip()]
    hints = _hints_from_parts(parts[1:])
    first_part = parts[0]
    province_hint = hints["province"]
    name, suffix_province = _split_province_suffix(first_part)
    if suffix_province:
        province_hint = suffix_province
    return _resolve_name(name, province_hint, hints["region"], country_hint)


def work_mode_of(raw_location: str | None) -> str:
    """'remote', 'hybrid' or '' (on site) as written in the location text."""
    text = raw_location or ""
    if _HYBRID_WORDS.search(text):
        return WORK_MODE_HYBRID
    if _REMOTE_WORDS.search(text):
        return WORK_MODE_REMOTE
    return WORK_MODE_ONSITE


def _hints_from_parts(parts: list[str]) -> dict[str, str]:
    hints = {"province": "", "region": ""}
    for part in parts:
        folded = fold_text(part)
        if folded in _REGION_WORDS:
            hints["region"] = _REGION_WORDS[folded]
        if part.upper() in _province_codes() and len(part) == 2:
            hints["province"] = part.upper()
    return hints


def _split_province_suffix(text: str) -> tuple[str, str]:
    cleaned = _POSTAL_CODE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/")
    match = _PROVINCE_SUFFIX.search(cleaned)
    if match is not None and match.group(1).upper() in _province_codes() and match.group(1).isupper():
        return cleaned[:match.start()].strip(), match.group(1).upper()
    return cleaned, ""


def _resolve_name(name: str, province_hint: str, region_hint: str, country_hint: str) -> Location:
    folded = fold_text(name)
    if folded in _REGION_WORDS:
        return Location(CERTAINTY_REGION_ONLY, region=_REGION_WORDS[folded])
    if folded in _COUNTRY_WORDS or any(marker in folded for marker in _VAGUE_MARKERS):
        return Location(CERTAINTY_REGION_ONLY, region=region_hint)
    name_without_suffix, suffix_country = _split_country_suffix(name)
    if suffix_country:
        country_hint = suffix_country
    found = find_place(name_without_suffix, province_hint, country_hint)
    if found.certainty == CERTAINTY_UNKNOWN:
        return Location(CERTAINTY_UNKNOWN, region=region_hint)
    return found


def _split_country_suffix(name: str) -> tuple[str, str]:
    """'Chiasso TI' or 'Chiasso CH' point to Switzerland."""
    words = name.split()
    if len(words) > 1 and fold_text(words[-1]) in ("ti", "ch"):
        return " ".join(words[:-1]), "CH"
    return name, ""


def classify_area(location: Location, policy: AreaPolicy) -> str:
    """Say whether a resolved location is inside the search area, outside, or uncertain."""
    if location.certainty == CERTAINTY_EXACT:
        return _classify_place(location.place, policy)
    if location.certainty == CERTAINTY_AMBIGUOUS:
        return _classify_candidates(location.candidates, policy)
    if location.certainty == CERTAINTY_REGION_ONLY and location.region:
        if location.region not in policy.regions:
            return AREA_OUT
    return AREA_UNCERTAIN


def _classify_place(place: Place, policy: AreaPolicy) -> str:
    if place.region not in policy.regions:
        return AREA_OUT
    if _place_is_included(place, policy.include_places):
        return AREA_IN
    if policy.radius_km is not None and policy.home is not None:
        distance = haversine_km(policy.home, (place.lat, place.lng))
        if distance <= policy.radius_km:
            return AREA_IN
        return AREA_OUT
    if policy.include_places:
        return AREA_OUT
    return AREA_IN


def _classify_candidates(candidates: tuple[Place, ...], policy: AreaPolicy) -> str:
    verdicts = {_classify_place(place, policy) for place in candidates}
    if verdicts == {AREA_IN}:
        return AREA_IN
    if verdicts == {AREA_OUT}:
        return AREA_OUT
    return AREA_UNCERTAIN


def _place_is_included(place: Place, include_places: frozenset[str]) -> bool:
    if not include_places:
        return False
    if place.province in include_places:
        return True
    return fold_text(place.name) in include_places


def places_in_radius(home: tuple[float, float], radius_km: float, regions: frozenset[str]) -> list[Place]:
    """All known places within the radius, nearest first."""
    nearby = []
    for place in load_places():
        if place.region not in regions:
            continue
        distance = haversine_km(home, (place.lat, place.lng))
        if distance <= radius_km:
            nearby.append((distance, place))
    nearby.sort(key=lambda item: item[0])
    return [place for _, place in nearby]
