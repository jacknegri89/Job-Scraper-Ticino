"""Place lookup, location certainty and the search area."""

import pytest

import geo
from geo import AreaPolicy, CERTAINTY_AMBIGUOUS, CERTAINTY_EXACT, CERTAINTY_REGION_ONLY, CERTAINTY_UNKNOWN


def _home_in_brianza() -> tuple[float, float]:
    place = geo.find_place("Seveso").place
    return place.lat, place.lng


def test_data_covers_lombardy_and_ticino() -> None:
    places = geo.load_places()
    countries = {place.country for place in places}
    assert countries == {"IT", "CH"}
    assert sum(1 for place in places if place.country == "IT") > 1000
    assert geo.find_place("Chiasso").place.region == "TI"
    assert geo.find_place("Monza").place.province == "MB"


@pytest.mark.parametrize("raw_text, expected_name, expected_region", [
    ("Monza MB", "Monza", "LOM"),
    ("Milano (MI)", "Milano", "LOM"),
    ("Lissone, MB, Lombardia, Italia", "Lissone", "LOM"),
    ("6830 Chiasso", "Chiasso", "TI"),
    ("Chiasso TI", "Chiasso", "TI"),
    ("CANTÙ", "Cantu", "LOM"),
])
def test_common_location_formats_resolve_to_an_exact_place(raw_text, expected_name, expected_region) -> None:
    location = geo.resolve_location(raw_text)
    assert location.certainty == CERTAINTY_EXACT
    assert geo.fold_text(location.place.name) == geo.fold_text(expected_name)
    assert location.region == expected_region


@pytest.mark.parametrize("raw_text", ["Lombardia", "Provincia di Varese", "Milano e hinterland", "Italia", "Da remoto"])
def test_generic_locations_are_never_given_a_city(raw_text) -> None:
    location = geo.resolve_location(raw_text)
    assert location.certainty == CERTAINTY_REGION_ONLY
    assert location.place is None


def test_unknown_and_empty_locations_stay_unknown() -> None:
    assert geo.resolve_location("").certainty == CERTAINTY_UNKNOWN
    assert geo.resolve_location(None).certainty == CERTAINTY_UNKNOWN
    assert geo.resolve_location("Cittanonesistente").certainty == CERTAINTY_UNKNOWN


def test_same_name_in_two_provinces_is_ambiguous_without_a_hint() -> None:
    names = {}
    for place in geo.load_places():
        names.setdefault(place.name, []).append(place)
    duplicated = next(name for name, found in names.items() if len({p.province for p in found}) > 1)
    assert geo.resolve_location(duplicated).certainty == CERTAINTY_AMBIGUOUS
    for place in names[duplicated]:
        hinted = geo.resolve_location(f"{duplicated} {place.province}")
        assert hinted.certainty == CERTAINTY_EXACT
        assert hinted.place == place


def test_radius_includes_nearby_places_in_both_regions_and_excludes_far_ones() -> None:
    policy = AreaPolicy(radius_km=30, home=_home_in_brianza())
    assert geo.classify_area(geo.resolve_location("Milano"), policy) == geo.AREA_IN
    assert geo.classify_area(geo.resolve_location("Chiasso"), policy) == geo.AREA_IN
    assert geo.classify_area(geo.resolve_location("Lugano"), policy) == geo.AREA_OUT
    assert geo.classify_area(geo.resolve_location("Brescia"), policy) == geo.AREA_OUT


def test_region_choice_limits_the_area() -> None:
    only_lombardy = AreaPolicy(regions=frozenset({"LOM"}), radius_km=30, home=_home_in_brianza())
    only_ticino = AreaPolicy(regions=frozenset({"TI"}), radius_km=30, home=_home_in_brianza())
    assert geo.classify_area(geo.resolve_location("Chiasso"), only_lombardy) == geo.AREA_OUT
    assert geo.classify_area(geo.resolve_location("Milano"), only_ticino) == geo.AREA_OUT
    assert geo.classify_area(geo.resolve_location("Chiasso"), only_ticino) == geo.AREA_IN


def test_included_places_and_provinces_bypass_the_radius() -> None:
    policy = AreaPolicy(radius_km=5, home=_home_in_brianza(), include_places=frozenset({"BS", "lugano"}))
    assert geo.classify_area(geo.resolve_location("Brescia"), policy) == geo.AREA_IN
    assert geo.classify_area(geo.resolve_location("Lugano"), policy) == geo.AREA_IN
    assert geo.classify_area(geo.resolve_location("Bergamo"), policy) == geo.AREA_OUT


def test_without_radius_or_home_the_whole_region_is_in_area() -> None:
    policy = AreaPolicy(regions=frozenset({"LOM"}))
    assert geo.classify_area(geo.resolve_location("Brescia"), policy) == geo.AREA_IN


def test_uncertain_locations_are_not_forced_in_or_out() -> None:
    policy = AreaPolicy(radius_km=30, home=_home_in_brianza())
    assert geo.classify_area(geo.resolve_location("Lombardia"), policy) == geo.AREA_UNCERTAIN
    assert geo.classify_area(geo.resolve_location("Cittanonesistente"), policy) == geo.AREA_UNCERTAIN
    only_ticino = AreaPolicy(regions=frozenset({"TI"}), radius_km=30, home=_home_in_brianza())
    assert geo.classify_area(geo.resolve_location("Lombardia"), only_ticino) == geo.AREA_OUT


def test_places_in_radius_are_sorted_nearest_first() -> None:
    nearby = geo.places_in_radius(_home_in_brianza(), 10, frozenset({"LOM"}))
    distances = [geo.haversine_km(_home_in_brianza(), (place.lat, place.lng)) for place in nearby]
    assert distances == sorted(distances)
    assert all(distance <= 10 for distance in distances)
