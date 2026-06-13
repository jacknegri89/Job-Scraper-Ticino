# Calcolo della distanza in km da Barlassina (MB) ai comuni di lavoro in Ticino.
# Usa la formula haversine (linea d'aria) su coordinate fisse — nessuna chiamata di rete.
# Il tragitto reale in auto è tipicamente il 20-35% più lungo.
#
# Uso:
#   from distance import km_da_barlassina
#   km_da_barlassina("Chiasso")        → 21.3
#   km_da_barlassina("6850 Mendrisio") → 26.7
#   km_da_barlassina("Zurigo")         → None  (comune non mappato)

from math import asin, cos, radians, sin, sqrt

from job_filter import normalize_city

_BARLASSINA = (45.6536, 9.1297)

# Coordinate (lat, lon) dei comuni ammessi nel distretto di Mendrisio.
_COORDINATE_COMUNI = {
    "chiasso":          (45.8320, 9.0310),
    "mendrisio":        (45.8703, 8.9817),
    "stabio":           (45.8487, 8.9367),
    "balerna":          (45.8460, 9.0080),
    "coldrerio":        (45.8530, 9.0040),
    "morbio inferiore": (45.8490, 9.0150),
    "novazzano":        (45.8400, 8.9810),
    "riva san vitale":  (45.9010, 8.9710),
}

_RAGGIO_TERRA_KM = 6371.0


def _haversine_km(da: tuple, a: tuple) -> float:
    lat1, lon1 = map(radians, da)
    lat2, lon2 = map(radians, a)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * _RAGGIO_TERRA_KM * asin(sqrt(h))


def km_da_barlassina(city_raw: str) -> float | None:
    # Accetta il campo città grezzo dal portale ("6850 Chiasso", "Mendrisio, TI", ecc.)
    comune = normalize_city(city_raw or "")
    coordinate = _COORDINATE_COMUNI.get(comune)
    if coordinate is None:
        return None
    return round(_haversine_km(_BARLASSINA, coordinate), 1)
