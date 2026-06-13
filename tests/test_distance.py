"""Test del modulo distance (km da Barlassina)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from distance import km_da_barlassina


def test_chiasso_distanza_plausibile():
    km = km_da_barlassina("Chiasso")
    assert km is not None
    assert 19 <= km <= 24          # linea d'aria nota: ~21 km


def test_riva_san_vitale_piu_lontana_di_chiasso():
    assert km_da_barlassina("Riva San Vitale") > km_da_barlassina("Chiasso")


def test_accetta_cap_e_suffissi():
    """Il campo città arriva grezzo dai portali: CAP, cantone, virgole."""
    assert km_da_barlassina("6850 Mendrisio") == km_da_barlassina("Mendrisio")
    assert km_da_barlassina("Stabio, TI") == km_da_barlassina("Stabio")
    assert km_da_barlassina("Balerna TI") == km_da_barlassina("Balerna")


def test_comune_sconosciuto_da_none():
    assert km_da_barlassina("Zurigo") is None
    assert km_da_barlassina("") is None
    assert km_da_barlassina(None) is None


def test_tutti_i_comuni_ammessi_mappati():
    """Ogni comune del filtro deve avere una distanza: mai badge mancanti."""
    from filters import COMUNI_AMMESSI
    for comune in COMUNI_AMMESSI:
        assert km_da_barlassina(comune) is not None, f"manca {comune}"
