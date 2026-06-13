"""Test di sanità del calcolo netto frontaliero (stime, non valori esatti)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from salary_calculator import calcola_netto


def test_input_non_valido_da_dizionario_vuoto():
    assert calcola_netto(0) == {}
    assert calcola_netto(-100) == {}
    assert calcola_netto(None) == {}


def test_netto_minore_del_lordo():
    r = calcola_netto(4000)
    assert 0 < r["netto_chf"] < 4000
    assert 0 < r["netto_eur"] < r["netto_chf"] / 0.9   # cambio ~0.96


def test_trattenute_positive():
    r = calcola_netto(3500)
    assert r["soc_chf"] > 0          # contributi sociali sempre dovuti
    assert r["qs_chf"] > 0           # imposta alla fonte sempre dovuta
    assert r["irpef_eur"] >= 0       # IRPEF può essere 0 (esenzione 10k CHF)


def test_stipendio_piu_alto_netto_piu_alto():
    """Il calcolo deve essere monotono: più lordo → più netto."""
    assert calcola_netto(5000)["netto_eur"] > calcola_netto(3000)["netto_eur"]


def test_campi_tutti_presenti_e_interi():
    r = calcola_netto(4200)
    for campo in ("lordo_chf", "soc_chf", "qs_chf", "irpef_eur",
                  "netto_chf", "netto_eur"):
        assert campo in r
        assert isinstance(r[campo], int)
