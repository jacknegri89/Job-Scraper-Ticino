"""Test del cuore del progetto: normalizzazione città, filtro comuni, dedup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from filters import (
    normalize_city, normalize_url, is_valid_job, filter_jobs, categorize_job,
)


def _job(**extra) -> dict:
    base = {
        "title": "Operaio",
        "company": "ACME SA",
        "city": "Chiasso",
        "date": "2026-06-10",
        "url": "https://example.ch/job/1",
        "source": "jobs.ch",
    }
    base.update(extra)
    return base


# ── normalize_city ──────────────────────────────────────────────

def test_normalize_city_formati_dei_portali():
    """Ogni portale scrive la città in modo diverso: tutti devono convergere."""
    assert normalize_city("Chiasso") == "chiasso"
    assert normalize_city("6850 Chiasso") == "chiasso"          # CAP davanti
    assert normalize_city("Chiasso, TI") == "chiasso"           # cantone dopo virgola
    assert normalize_city("Chiasso (TI)") == "chiasso"          # cantone tra parentesi
    assert normalize_city("Chiasso TI") == "chiasso"            # sigla senza virgola
    assert normalize_city("Mendrisiotto - Chiasso") == "chiasso"  # prefisso zona


# ── is_valid_job ────────────────────────────────────────────────

def test_comune_ammesso_passa():
    assert is_valid_job(_job(city="Mendrisio")) is True


def test_comune_fuori_zona_scartato():
    assert is_valid_job(_job(city="Lugano")) is False
    assert is_valid_job(_job(city="Zurigo")) is False


def test_portale_italiano_scartato():
    """Annunci su domini .it sono lavori in Italia, non frontalierato."""
    assert is_valid_job(_job(url="https://www.subito.it/annuncio/5")) is False


# ── filter_jobs: dedup ──────────────────────────────────────────

def test_dedup_per_url_identico():
    a = _job()
    b = _job(title="Operaio (copia)")          # stesso URL
    assert len(filter_jobs([a, b])) == 1


def test_dedup_cross_portale_stesso_contenuto():
    """Stesso annuncio pubblicato su due portali → tenuto una volta sola."""
    a = _job(url="https://www.jobs.ch/job/1")
    b = _job(url="https://www.jobscout24.ch/job/9", source="jobscout24.ch")
    assert len(filter_jobs([a, b])) == 1


def test_agenzie_non_deduplicate_per_titolo():
    """Le agenzie ripetono titolo+azienda: posizioni diverse NON vanno fuse."""
    a = _job(source="randstad.ch", company="Randstad SA",
             url="https://www.randstad.ch/it/lavoro/operaio_chiasso_aaaa1111-22bb/")
    b = _job(source="randstad.ch", company="Randstad SA",
             url="https://www.randstad.ch/it/lavoro/operaio_chiasso_cccc3333-44dd/")
    assert len(filter_jobs([a, b])) == 2


def test_ordinamento_data_decrescente():
    # Titoli diversi: altrimenti il dedup per contenuto li fonderebbe
    vecchio = _job(title="Saldatore",     date="2026-05-01", url="https://x.ch/1")
    nuovo   = _job(title="Magazziniere",  date="2026-06-12", url="https://x.ch/2")
    eu      = _job(title="Elettricista",  date="11.06.2026", url="https://x.ch/3")
    risultato = filter_jobs([vecchio, nuovo, eu])
    assert [j["date"] for j in risultato] == ["2026-06-12", "11.06.2026", "2026-05-01"]


def test_url_senza_tracking_uguali():
    pulito  = normalize_url("https://x.ch/job?id=5")
    sporco  = normalize_url("https://x.ch/job?id=5&utm_source=feed&utm_medium=x")
    assert pulito == sporco


# ── categorize_job ──────────────────────────────────────────────

def test_categorie_da_titolo():
    assert categorize_job("Magazziniere turno notte") == "logistica"
    assert categorize_job("Elettricista AFC") == "tech"
    assert categorize_job("Cameriere di sala") == "ristorazione"
    assert categorize_job("Direttore generale") == "altro"
