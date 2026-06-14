"""Offline great-circle distances from the configured home point."""

from math import asin, cos, radians, sin, sqrt

from job_filter import normalize_city

try:
    from user_config import HOME_CITY, HOME_LAT, HOME_LNG
except ImportError:
    HOME_LAT = 45.0
    HOME_LNG = 9.0
    HOME_CITY = "Home"

HOME_LAT = float(HOME_LAT)
HOME_LNG = float(HOME_LNG)
HOME_CITY = str(HOME_CITY)

_HOME_COORDINATES: tuple[float, float] = (HOME_LAT, HOME_LNG)
_EARTH_RADIUS_KM = 6371.0

_CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "chiasso": (45.8320, 9.0310),
    "mendrisio": (45.8703, 8.9817),
    "stabio": (45.8487, 8.9367),
    "balerna": (45.8460, 9.0080),
    "coldrerio": (45.8530, 9.0040),
    "morbio inferiore": (45.8490, 9.0150),
    "novazzano": (45.8400, 8.9810),
    "riva san vitale": (45.9010, 8.9710),
}


def _haversine_km(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> float:
    origin_lat, origin_lng = map(radians, origin)
    destination_lat, destination_lng = map(radians, destination)
    delta_lat = destination_lat - origin_lat
    delta_lng = destination_lng - origin_lng
    half_chord = (
        sin(delta_lat / 2) ** 2
        + cos(origin_lat) * cos(destination_lat) * sin(delta_lng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(half_chord))


def km_from_home(city_raw: str | None) -> float | None:
    """Return the distance from home to a supported city, in kilometers."""
    city = normalize_city(city_raw or "")
    coordinates = _CITY_COORDINATES.get(city)
    if coordinates is None:
        return None
    return round(_haversine_km(_HOME_COORDINATES, coordinates), 1)


def km_da_casa(city_raw: str | None) -> float | None:
    """Return kilometers from home; kept for dashboard compatibility."""
    return km_from_home(city_raw)


__all__ = ["HOME_CITY", "km_from_home", "km_da_casa"]
