"""
Distanza in chilometri da Barlassina (MB) ai comuni di lavoro in Ticino.

La distanza è calcolata in linea d'aria (formula dell'emisenoverso) tra
coordinate fisse: nessuna chiamata di rete, risultato sempre disponibile.
Il tragitto in auto reale è tipicamente il 20-35% più lungo.

Uso:
    from distance import km_da_barlassina
    km_da_barlassina("Chiasso")        → 21.3
    km_da_barlassina("6850 Mendrisio") → 26.7
    km_da_barlassina("Zurigo")         → None  (comune non in elenco)
"""

from math import asin, cos, radians, sin, sqrt

from filters import normalize_city

# Casa di partenza: Barlassina (Monza-Brianza)
_BARLASSINA = (45.6536, 9.1297)

# Coordinate (lat, lon) dei comuni ammessi — distretto di Mendrisio
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
    """Distanza in linea d'aria fra due coppie (lat, lon), in km."""
    lat1, lon1 = map(radians, da)
    lat2, lon2 = map(radians, a)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * _RAGGIO_TERRA_KM * asin(sqrt(h))


def km_da_barlassina(city_raw: str) -> float | None:
    """
    Km in linea d'aria da Barlassina al comune dell'annuncio.
    Accetta il campo città grezzo ("6850 Chiasso", "Mendrisio, TI", …).
    Ritorna None se il comune non è fra quelli mappati.
    """
    comune = normalize_city(city_raw or "")
    coordinate = _COORDINATE_COMUNI.get(comune)
    if coordinate is None:
        return None
    return round(_haversine_km(_BARLASSINA, coordinate), 1)
