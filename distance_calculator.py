"""Offline great-circle distances from the configured home point.

A distance is only given for an exact place. Generic text such as "Lombardia" or a
name shared by several places gets no distance.
"""

import geo

try:
    from user_config import HOME_CITY, HOME_LAT, HOME_LNG
except ModuleNotFoundError as error:
    if error.name != "user_config":
        raise
    # No personal config: there is no home point, so distances stay hidden.
    HOME_LAT = None
    HOME_LNG = None
    HOME_CITY = "Home"

HOME_CITY = str(HOME_CITY)

_HOME_COORDINATES: tuple[float, float] | None = None
if HOME_LAT is not None and HOME_LNG is not None:
    HOME_LAT = float(HOME_LAT)
    HOME_LNG = float(HOME_LNG)
    _HOME_COORDINATES = (HOME_LAT, HOME_LNG)


def is_home_configured() -> bool:
    """True when a home point is set; otherwise no distance can be shown."""
    return _HOME_COORDINATES is not None


def km_from_home(city_raw: str | None, country_hint: str = "") -> float | None:
    """Return the distance from home to an exactly known place, in kilometers."""
    if _HOME_COORDINATES is None:
        return None
    location = geo.resolve_location(city_raw or "", country_hint)
    if location.certainty != geo.CERTAINTY_EXACT:
        return None
    place = location.place
    return round(geo.haversine_km(_HOME_COORDINATES, (place.lat, place.lng)), 1)


def km_da_casa(city_raw: str | None) -> float | None:
    """Return kilometers from home; kept for dashboard compatibility."""
    return km_from_home(city_raw)


__all__ = ["HOME_CITY", "is_home_configured", "km_from_home", "km_da_casa"]
