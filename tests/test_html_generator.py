"""Test di fumo del generatore dashboard."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_builder import generate_html, build_card


def _job(**extra) -> dict:
    base = {
        "title": "Operaio di produzione",
        "company": "Rossi SA",
        "city": "Chiasso",
        "date": "2026-06-10",
        "url": "https://www.jobs.ch/it/annuncio/123",
        "category": "produzione",
        "source": "jobs.ch",
    }
    base.update(extra)
    return base


def test_card_mostra_distanza_da_barlassina():
    card = build_card(_job())
    assert "Da Barlassina" in card
    assert "21 km" in card           # Chiasso ≈ 21.3 → mostrato come "21 km"
    assert 'data-km="21.3"' in card  # attributo per l'ordinamento "più vicini"


def test_card_comune_ignoto_mostra_trattino():
    card = build_card(_job(city="Lugano"))
    assert 'data-km="9999"' in card  # in fondo quando si ordina per distanza
    assert "—" in card


def test_card_escapa_html_nei_campi():
    card = build_card(_job(title='<script>alert("x")</script>'))
    assert "<script>alert" not in card
    assert "&lt;script&gt;" in card


def test_card_url_non_http_diventa_cancelletto():
    card = build_card(_job(url="javascript:alert(1)"))
    assert 'href="#"' in card
    assert "javascript:alert" not in card


def test_generate_html_scrive_pagina_completa(tmp_path):
    out = tmp_path / "index.html"
    generate_html([_job(), _job(city="Mendrisio", title="Magazziniere",
                               category="logistica")], str(out))
    pagina = out.read_text(encoding="utf-8")
    assert pagina.startswith("<!DOCTYPE html>")
    assert "__CARDS__" not in pagina          # nessun segnaposto dimenticato
    assert "__COUNT__" not in pagina
    assert pagina.count("<article") == 2
    assert "Più vicini" in pagina             # ordinamento per distanza presente


def test_generate_html_zero_annunci_mostra_stato_vuoto(tmp_path):
    out = tmp_path / "vuota.html"
    generate_html([], str(out))
    pagina = out.read_text(encoding="utf-8")
    assert 'class="empty show"' in pagina
