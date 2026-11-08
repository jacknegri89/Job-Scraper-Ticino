"""What the user wants to see: area, fields, seniority, contract and freshness."""

from dataclasses import dataclass, field

from geo import ALL_REGIONS, AreaPolicy, fold_text

DEFAULT_RADIUS_KM = 30
DEFAULT_EXPIRY_DAYS = 14
DEFAULT_RETENTION_DAYS = 60
DEFAULT_VERIFY_LIMIT = 15
MAX_RADIUS_KM = 300
MAX_DAYS = 365
# Paid AI calls are capped per run, newest listings first; the rest wait for the next run.
DEFAULT_AI_MAX_PER_RUN = 25
MAX_AI_PER_RUN = 200


@dataclass(frozen=True)
class SearchPreferences:
    """Filters applied to every collected job. None means 'no restriction'."""

    area: AreaPolicy = field(default_factory=AreaPolicy)
    include_uncertain_location: bool = False
    include_remote: bool = False
    categories: frozenset[str] | None = None
    seniority_levels: frozenset[str] | None = None
    contract_types: frozenset[str] | None = None
    expiry_days: int = DEFAULT_EXPIRY_DAYS
    retention_days: int = DEFAULT_RETENTION_DAYS
    verify_limit: int = DEFAULT_VERIFY_LIMIT


def preferences_from_settings(settings: dict) -> SearchPreferences:
    """Build the preferences from validated settings (see startup_config.py)."""
    home = _home_from_settings(settings)
    area = AreaPolicy(
        regions=frozenset(settings.get("regions") or ALL_REGIONS),
        radius_km=settings.get("radius_km"),
        home=home,
        include_places=_include_places(settings.get("include_places") or []),
    )
    return SearchPreferences(
        area=area,
        include_uncertain_location=bool(settings.get("include_uncertain_location", False)),
        include_remote=bool(settings.get("include_remote", False)),
        categories=_optional_set(settings.get("categories")),
        seniority_levels=_optional_set(settings.get("seniority_levels")),
        contract_types=_optional_set(settings.get("contract_types")),
        expiry_days=int(settings.get("expiry_days", DEFAULT_EXPIRY_DAYS)),
        retention_days=int(settings.get("retention_days", DEFAULT_RETENTION_DAYS)),
        verify_limit=int(settings.get("verify_limit", DEFAULT_VERIFY_LIMIT)),
    )


def _home_from_settings(settings: dict) -> tuple[float, float] | None:
    latitude = settings.get("home_lat")
    longitude = settings.get("home_lng")
    if latitude is None or longitude is None:
        return None
    return float(latitude), float(longitude)


def _include_places(places: list[str]) -> frozenset[str]:
    """Province codes stay upper-case; place names are folded for comparison."""
    included = set()
    for text in places:
        stripped = str(text).strip()
        if len(stripped) == 2 and stripped.isalpha():
            included.add(stripped.upper())
        if stripped:
            included.add(fold_text(stripped))
    return frozenset(included)


def _optional_set(values: list[str] | None) -> frozenset[str] | None:
    if not values:
        return None
    return frozenset(values)

