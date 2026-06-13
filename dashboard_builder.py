"""
Generatore della dashboard index.html.

Design: tema scuro semplice e leggibile, una colonna di controlli
(ricerca, filtri categoria, filtro AI, ordinamento) e una griglia di card.
Ogni card mostra anche la distanza in km da Barlassina (linea d'aria).

Struttura del file:
  - costanti di presentazione (CATEGORY, SOURCE_LABEL)
  - pulizia descrizioni grezze (_clean_raw)
  - helper di card: ogni blocco HTML ha la sua funzione nominata
  - build_card: assembla i blocchi
  - generate_html: statistiche + sostituzione segnaposto nel template
"""

import html as html_lib
from datetime import datetime
from pathlib import Path

from distance_calculator import km_da_barlassina
from salary_calculator import calcola_netto

# category_id: (colore_puntino, etichetta)
CATEGORY = {
    "tech":         ("#79B8FF", "Tech / IT"),
    "logistica":    ("#7EE2A8", "Logistica"),
    "produzione":   ("#76E3EA", "Produzione"),
    "ristorazione": ("#FF9EC1", "Ristorazione"),
    "pulizie":      ("#FFD47E", "Pulizie"),
    "retail":       ("#FFB07C", "Retail"),
    "trasporti":    ("#BFA9FF", "Trasporti"),
    "altro":        ("#9AA0A6", "Altro"),
}

SOURCE_LABEL = {
    "jobs.ch":              "jobs.ch",
    "carriera.ch":          "carriera.ch",
    "gigroup.ch":           "Gi Group",
    "randstad.ch":          "Randstad",
    "orienta.ch":           "Orienta",
    "jobscout24.ch":        "JobScout24",
    "indeed.ch":            "Indeed",
    "monster.ch":           "Monster",
    "adecco.ch":            "Adecco",
    "manpower.ch":          "Manpower",
    "frontaliereticino.ch": "Frontalieri Ticino",
    "linkedin.ch":          "LinkedIn",
}


def _e(testo) -> str:
    """Escape HTML."""
    return html_lib.escape(str(testo))


# ────────────────────────────────────────────────────────────────
# Pulizia del testo grezzo delle descrizioni
# ────────────────────────────────────────────────────────────────

# Sottostringhe sicure: presenti SOLO in navigazione/boilerplate dei portali
_JUNK = frozenset([
    "home / offerte di lavoro", "candidati ora", "inserisci la tua email",
    "dettagli offerta di lavoro", "dettagli dell'annuncio",
    "log in,", "save apply", "per candidarti",
    "mostra offerte simili", "imposta un job alert",
    "prodotti metallurgici", "elettronica e semiconduttori",
    "edilizia e costruzioni", "gestione progetti", "electrics",
    "classe e stipendio annuo", "sede di lavoro:", "tipo di lavoro:",
])

# Termini ambigui: scartano il segmento solo se appare ALL'INIZIO
_JUNK_PREFIX = (
    "registrati", "login", "opportunit", "inserisci la tua",
    "dettagli dell", "offerta:", "soggetto:",
)

# Prefissi-etichetta da togliere dall'inizio di ogni segmento
_LABEL_PREFIX = ("descrizione:", "dettagli:", "offerta di lavoro:", "soggetto:")


def _strip_label_prefix(segmento: str) -> str:
    """'Descrizione: testo…' → 'testo…'"""
    minuscolo = segmento.lower()
    for etichetta in _LABEL_PREFIX:
        if minuscolo.startswith(etichetta):
            return segmento[len(etichetta):].strip()
    return segmento


def _is_junk(segmento: str) -> bool:
    minuscolo = segmento.lower()
    if len(segmento) < 20:
        return True
    if any(j in minuscolo for j in _JUNK):
        return True
    return minuscolo.startswith(_JUNK_PREFIX)


def _clean_raw(testo: str) -> str:
    """Filtra il testo grezzo: rimuove breadcrumb, pulsanti, metadati form."""
    segmenti = [s.strip() for s in testo.split(" | ") if s.strip()]
    buoni = []
    for segmento in segmenti:
        segmento = _strip_label_prefix(segmento)
        if not _is_junk(segmento):
            buoni.append(segmento)
    return " ".join(buoni)


# ────────────────────────────────────────────────────────────────
# Blocchi della card — una funzione per blocco
# ────────────────────────────────────────────────────────────────

def _desc_html(job: dict) -> str:
    """Descrizione: preferisce quella dell'AI, altrimenti testo grezzo pulito."""
    llm_desc = job.get("llm_descrizione", "").strip()
    if llm_desc:
        return _e(llm_desc).replace("\n", "<br>")

    raw = job.get("description", "").strip()
    if not raw:
        return ""
    pulito = _clean_raw(raw)
    if not pulito:
        return ""
    troncato = pulito[:700] + ("…" if len(pulito) > 700 else "")
    return _e(troncato)


def _desc_block(job: dict) -> str:
    corpo = _desc_html(job)
    if not corpo:
        return ""
    return f'<p class="card-desc">{corpo}</p>'


def _ai_block(job: dict) -> tuple[str, str]:
    """
    Ritorna (valore data-ai, blocco HTML del verdetto AI).
    data-ai: "adatto" | "non_adatto" | "none" — usato dal filtro in pagina.
    """
    adatto = job.get("llm_adatto")
    motivo = _e(job.get("llm_motivo", ""))
    motivo_html = f'<p class="ai-why">{motivo}</p>' if motivo else ""

    if adatto is True:
        return "adatto", (
            '<div class="ai ai-ok"><span class="ai-ico">✔</span><div>'
            '<span class="ai-tag">Adatto a te</span>' + motivo_html + "</div></div>"
        )
    if adatto is False:
        return "non_adatto", (
            '<div class="ai ai-no"><span class="ai-ico">✕</span><div>'
            '<span class="ai-tag">Non adatto</span>' + motivo_html + "</div></div>"
        )
    return "none", ""


def _salary_block(job: dict) -> str:
    """Pannello stipendio: lordo CH → trattenute → netto stimato in Italia."""
    lordo = job.get("llm_stipendio_lordo")
    if not lordo:
        return ""
    tax = calcola_netto(lordo)
    if not tax:
        return ""
    return (
        '<div class="salary">'
        '<div class="sal-head">Stipendio stimato</div>'
        f'<div class="sal-row"><span>Lordo CH</span>'
        f'<span class="sal-num">{tax["lordo_chf"]:,} CHF</span></div>'
        f'<div class="sal-row deduct"><span>Contributi sociali CH</span>'
        f'<span class="sal-num">−{tax["soc_chf"]:,} CHF</span></div>'
        f'<div class="sal-row deduct"><span>Imposta alla fonte TI</span>'
        f'<span class="sal-num">−{tax["qs_chf"]:,} CHF</span></div>'
        f'<div class="sal-row deduct"><span>IRPEF aggiuntiva IT</span>'
        f'<span class="sal-num">−{tax["irpef_eur"]:,} €</span></div>'
        f'<div class="sal-net"><span>Netto in Italia</span>'
        f'<span>~{tax["netto_eur"]:,} €/mese</span></div>'
        '<p class="sal-note">Stima ±15% · regime frontaliero post 17/07/2023</p>'
        "</div>"
    )


def _email_block(job: dict) -> str:
    email = job.get("email", "").strip()
    if not email:
        return ""
    email = _e(email)
    return f'<a class="email-link" href="mailto:{email}">✉ {email}</a>'


def _distance_of(job: dict) -> float | None:
    return km_da_barlassina(job.get("city", ""))


def _distance_label(km: float | None) -> str:
    if km is None:
        return "—"
    return f"{km:.0f} km"


def _safe_url(job: dict) -> str:
    url = job.get("url", "")
    if url.startswith(("https://", "http://")):
        return _e(url)
    return "#"


def _search_blob(job: dict) -> str:
    """Testo minuscolo usato dalla ricerca live."""
    campi = (job.get("title", ""), job.get("company", ""),
             job.get("city", ""), job.get("email", ""))
    return _e(" ".join(campi).lower())


# ────────────────────────────────────────────────────────────────
# Card completa
# ────────────────────────────────────────────────────────────────

def build_card(job: dict) -> str:
    categoria = job.get("category", "altro")
    colore, etichetta_cat = CATEGORY.get(categoria, CATEGORY["altro"])
    fonte = SOURCE_LABEL.get(job.get("source", ""), _e(job.get("source", "")))

    km = _distance_of(job)
    km_attr = f"{km:.1f}" if km is not None else "9999"   # 9999 = in fondo nell'ordinamento

    ai_filter, ai_html = _ai_block(job)

    return f"""<article class="card" data-category="{_e(categoria)}" data-ai="{ai_filter}"
  data-km="{km_attr}" data-search="{_search_blob(job)}" style="--accent:{colore}">
  <div class="card-head">
    <span class="card-cat"><span class="cat-dot"></span>{etichetta_cat}</span>
    <span class="card-source">{fonte}</span>
  </div>
  <h2 class="card-title">{_e(job.get("title", ""))}</h2>
  <p class="card-company">{_e(job.get("company", "")) or "&nbsp;"}</p>
  {_desc_block(job)}
  {ai_html}
  <div class="card-meta">
    <div><span class="meta-k">Luogo</span><span class="meta-v">{_e(job.get("city", ""))}</span></div>
    <div><span class="meta-k">Da Barlassina</span><span class="meta-v">{_distance_label(km)}</span></div>
    <div><span class="meta-k">Pubblicato</span><span class="meta-v">{_e(job.get("date", "")) or "—"}</span></div>
  </div>
  {_salary_block(job)}
  {_email_block(job)}
  <a class="apply-btn" href="{_safe_url(job)}" target="_blank" rel="noopener noreferrer">
    Candidati <span class="arrow">→</span>
  </a>
</article>"""


# ────────────────────────────────────────────────────────────────
# Template pagina
# ────────────────────────────────────────────────────────────────

_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lavoro Ticino — dashboard frontaliere</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2214%22 fill=%22%23161B22%22/><text x=%2232%22 y=%2243%22 font-size=%2230%22 text-anchor=%22middle%22 fill=%22%233FB950%22>●</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg:     #0E1116;
  --panel:  #161B22;
  --panel2: #1C232C;
  --line:   #262D37;
  --line2:  #39414D;
  --text:   #E6EDF3;
  --muted:  #9BA4AF;
  --faint:  #6A7380;
  --green:  #3FB950;
  --green-dim: rgba(63,185,80,.12);
  --red:    #F47067;
  --font:   'Inter', -apple-system, 'Segoe UI', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: var(--font); font-size: 14px; line-height: 1.5;
}
::selection { background: var(--green); color: #fff; }

/* ── Header ───────────────────────────────────────── */
header {
  max-width: 1280px; margin: 0 auto;
  padding: 40px 24px 28px;
}
.h-top { display: flex; justify-content: space-between; align-items: baseline;
         flex-wrap: wrap; gap: 8px; }
h1 { font-size: 26px; font-weight: 800; letter-spacing: -.02em; }
h1 .dot { color: var(--green); }
.updated { color: var(--faint); font-size: 13px; }
.subtitle { color: var(--muted); margin-top: 6px; font-size: 14px; }

.stats { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 22px; }
.stat {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 14px 22px; min-width: 130px;
}
.stat b { display: block; font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat.green b { color: var(--green); }
.stat span { color: var(--faint); font-size: 12px; font-weight: 500; }

/* ── Toolbar ──────────────────────────────────────── */
.toolbar {
  position: sticky; top: 0; z-index: 50;
  background: rgba(14,17,22,.92);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.toolbar-in {
  max-width: 1280px; margin: 0 auto; padding: 12px 24px;
  display: flex; flex-direction: column; gap: 10px;
}
.row1 { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
#search {
  flex: 1; min-width: 220px; max-width: 420px;
  background: var(--panel); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px;
  padding: 9px 14px; font-size: 13.5px; font-family: var(--font);
  outline: none;
}
#search:focus { border-color: var(--green); }
#search::placeholder { color: var(--faint); }
#sort {
  background: var(--panel); color: var(--muted);
  border: 1px solid var(--line); border-radius: 8px;
  padding: 9px 10px; font-size: 13px; font-family: var(--font);
  outline: none; cursor: pointer;
}
.count { color: var(--faint); font-size: 13px; white-space: nowrap; }
.count b { color: var(--green); }

.chips { display: flex; flex-wrap: wrap; gap: 7px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  background: var(--panel); color: var(--muted);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 6px 13px; cursor: pointer;
  font-family: var(--font); font-size: 12.5px; font-weight: 600;
}
.chip:hover { border-color: var(--line2); color: var(--text); }
.chip.active { background: var(--text); color: var(--bg); border-color: var(--text); }
.chip .n { opacity: .55; font-weight: 500; }
.chip-dot { width: 7px; height: 7px; border-radius: 50%;
            background: var(--chip-accent, var(--faint)); }
.chip-ai { border-color: rgba(63,185,80,.4); color: var(--green); }
.chip-ai.active { background: var(--green); color: #fff; border-color: var(--green); }

/* ── Griglia card ─────────────────────────────────── */
main { max-width: 1280px; margin: 0 auto; padding: 24px 24px 80px; }
.grid {
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
}
.card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 14px; padding: 20px;
  display: flex; flex-direction: column; gap: 12px;
  transition: border-color .15s, transform .15s;
}
.card:hover { border-color: var(--line2); transform: translateY(-2px); }
.card[data-ai="non_adatto"] { opacity: .45; }
.card[data-ai="non_adatto"]:hover { opacity: 1; }

.card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.card-cat {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 11.5px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .05em;
}
.cat-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.card-source {
  font-size: 11px; font-weight: 600; color: var(--faint);
  border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px;
  white-space: nowrap;
}
.card-title { font-size: 16.5px; font-weight: 700; line-height: 1.3; }
.card-company { color: var(--muted); font-size: 13px; margin-top: -6px; }

.card-desc {
  color: #C9D1D9; font-size: 13px; line-height: 1.65;
  background: var(--panel2); border-radius: 10px; padding: 12px 14px;
}

.ai { display: flex; gap: 10px; padding: 11px 14px; border-radius: 10px; }
.ai-ok { background: var(--green-dim); }
.ai-no { background: rgba(244,112,103,.08); }
.ai-ico { font-size: 13px; }
.ai-ok .ai-ico { color: var(--green); }
.ai-no .ai-ico { color: var(--red); }
.ai-tag { font-size: 12.5px; font-weight: 700; }
.ai-ok .ai-tag { color: var(--green); }
.ai-no .ai-tag { color: var(--red); }
.ai-why { font-size: 12.5px; color: var(--muted); margin-top: 3px; }

.card-meta {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  border-top: 1px solid var(--line); padding-top: 12px; margin-top: auto;
}
.meta-k { display: block; font-size: 10.5px; color: var(--faint);
          font-weight: 600; text-transform: uppercase; letter-spacing: .04em;
          margin-bottom: 2px; }
.meta-v { font-size: 13px; font-weight: 600; }

.salary { background: var(--panel2); border-radius: 10px;
          padding: 13px 14px 10px; display: flex; flex-direction: column; gap: 6px; }
.sal-head { font-size: 10.5px; color: var(--faint); font-weight: 700;
            text-transform: uppercase; letter-spacing: .05em;
            border-bottom: 1px solid var(--line); padding-bottom: 7px; }
.sal-row { display: flex; justify-content: space-between; font-size: 12.5px;
           color: var(--muted); }
.sal-num { font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.sal-row.deduct .sal-num { color: var(--red); }
.sal-net { display: flex; justify-content: space-between; align-items: center;
           background: var(--green); color: #fff; font-size: 13px; font-weight: 700;
           padding: 8px 12px; border-radius: 8px; margin-top: 4px; }
.sal-note { font-size: 10px; color: var(--faint); }

.email-link {
  font-size: 12.5px; font-weight: 600; color: var(--muted);
  text-decoration: none; border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 12px; text-align: center; word-break: break-all;
}
.email-link:hover { border-color: var(--green); color: var(--green); }

.apply-btn {
  display: flex; justify-content: center; align-items: center; gap: 8px;
  background: var(--green); color: #fff;
  font-size: 13.5px; font-weight: 700;
  padding: 11px; border-radius: 8px; text-decoration: none;
}
.apply-btn:hover { filter: brightness(1.12); }
.apply-btn .arrow { transition: transform .15s; }
.apply-btn:hover .arrow { transform: translateX(3px); }

/* ── Stato vuoto / footer ─────────────────────────── */
.empty { display: none; text-align: center; padding: 70px 20px; color: var(--muted); }
.empty.show { display: block; }
.empty h3 { font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 8px; }

footer {
  border-top: 1px solid var(--line); text-align: center;
  padding: 26px 24px 40px; color: var(--faint); font-size: 12px; line-height: 1.9;
}

::-webkit-scrollbar { width: 9px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--line2); border-radius: 99px; }

@media (max-width: 640px) {
  .card-meta { grid-template-columns: 1fr 1fr; }
  h1 { font-size: 22px; }
}
</style>
</head>
<body>

<header>
  <div class="h-top">
    <h1><span class="dot">●</span> Lavoro Ticino</h1>
    <span class="updated">Aggiornato il __NOW__</span>
  </div>
  <p class="subtitle">Annunci da __NSOURCES__ portali svizzeri, filtrati sul
     distretto di Mendrisio. Distanze calcolate da Barlassina (linea d'aria).</p>
  <div class="stats">
    <div class="stat"><b>__COUNT__</b><span>annunci attivi</span></div>
    <div class="stat green"><b>__N_ADATTI__</b><span>adatti a te</span></div>
    <div class="stat"><b>__NSOURCES__</b><span>portali</span></div>
  </div>
</header>

<div class="toolbar">
  <div class="toolbar-in">
    <div class="row1">
      <input id="search" type="text" placeholder="Cerca titolo, azienda o città…">
      <select id="sort">
        <option value="date">Più recenti</option>
        <option value="km">Più vicini</option>
      </select>
      <span class="count"><b id="visible-n">__COUNT__</b> risultati</span>
    </div>
    <div class="chips">
      <button class="chip active" data-cat="all">Tutti <span class="n">__COUNT__</span></button>
      __CAT_CHIPS__
      <button class="chip chip-ai" id="chip-ai">✔ Adatti a me__CHIP_AI_N__</button>
    </div>
  </div>
</div>

<main>
  <div class="grid" id="grid">
__CARDS__
  </div>
  <div class="empty" id="empty">
    <h3>Nessun risultato</h3>
    <p>__EMPTY_SUB__</p>
  </div>
</main>

<footer>
  Fonti: __SOURCELIST__<br>
  Dashboard frontaliere · stipendi e distanze sono stime indicative
</footer>

<script>
"use strict";

const state = { cat: "all", ai: false, q: "" };
const grid  = document.getElementById("grid");
const cards = Array.from(grid.querySelectorAll(".card"));

// Ordine originale (= più recenti, già ordinato dal generatore)
cards.forEach((c, i) => { c.dataset.order = i; });

function applyFilters() {
  let visibili = 0;
  for (const card of cards) {
    const okCat = state.cat === "all" || card.dataset.category === state.cat;
    const okAI  = !state.ai || card.dataset.ai === "adatto";
    const okQ   = !state.q  || card.dataset.search.includes(state.q);
    const show  = okCat && okAI && okQ;
    card.style.display = show ? "" : "none";
    if (show) visibili++;
  }
  document.getElementById("visible-n").textContent = visibili;
  document.getElementById("empty").classList.toggle("show", visibili === 0);
}

function applySort(mode) {
  const sorted = [...cards];
  if (mode === "km") {
    sorted.sort((a, b) => parseFloat(a.dataset.km) - parseFloat(b.dataset.km));
  } else {
    sorted.sort((a, b) => a.dataset.order - b.dataset.order);
  }
  for (const card of sorted) grid.appendChild(card);
}

// Ricerca live
document.getElementById("search").addEventListener("input", (e) => {
  state.q = e.target.value.toLowerCase().trim();
  applyFilters();
});

// Ordinamento
document.getElementById("sort").addEventListener("change", (e) => {
  applySort(e.target.value);
});

// Chip categorie (delegato: un solo listener)
document.querySelector(".chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;

  if (chip.id === "chip-ai") {
    state.ai = !state.ai;
    chip.classList.toggle("active", state.ai);
  } else {
    state.cat = chip.dataset.cat;
    document.querySelectorAll(".chip[data-cat]").forEach(b => b.classList.remove("active"));
    chip.classList.add("active");
  }
  applyFilters();
});

// "/" focalizza la ricerca
addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement.tagName !== "INPUT") {
    e.preventDefault();
    document.getElementById("search").focus();
  }
});
</script>

</body>
</html>
"""


# ────────────────────────────────────────────────────────────────
# Generazione pagina
# ────────────────────────────────────────────────────────────────

def _conta_per_categoria(jobs: list) -> dict:
    conteggi: dict[str, int] = {}
    for job in jobs:
        categoria = job.get("category", "altro")
        conteggi[categoria] = conteggi.get(categoria, 0) + 1
    return conteggi


def _chips_categorie(conteggi: dict) -> str:
    """Un bottone-chip per ogni categoria presente (ordine di CATEGORY)."""
    chips = []
    for cat_id, (colore, etichetta) in CATEGORY.items():
        n = conteggi.get(cat_id, 0)
        if n == 0:
            continue
        chips.append(
            f'<button class="chip" data-cat="{cat_id}" style="--chip-accent:{colore}">'
            f'<span class="chip-dot"></span>{etichetta} <span class="n">{n}</span></button>'
        )
    return "\n      ".join(chips)


def _lista_fonti(jobs: list) -> tuple[int, str]:
    """(numero portali, elenco leggibile) dalle fonti realmente presenti."""
    presenti = {j.get("source", "") for j in jobs if j.get("source")}
    if not presenti:
        return len(SOURCE_LABEL), " · ".join(SOURCE_LABEL.values())
    nomi = sorted(SOURCE_LABEL.get(s, s) for s in presenti)
    return len(presenti), " · ".join(nomi)


def generate_html(jobs: list, output_path: str = "index.html") -> None:
    adesso = datetime.now().strftime("%d/%m/%Y · %H:%M")
    totale = len(jobs)
    adatti = sum(1 for j in jobs if j.get("llm_adatto") is True)
    conteggi = _conta_per_categoria(jobs)
    n_fonti, elenco_fonti = _lista_fonti(jobs)

    cards = "\n".join(build_card(job) for job in jobs)
    chip_ai_n = f' <span class="n">{adatti}</span>' if adatti else ""
    empty_sub = ("Prova a cambiare i filtri o la ricerca." if jobs
                 else "Nessun annuncio in cache: esegui python scraper.py")

    pagina = (_TEMPLATE
        .replace("__NOW__",        _e(adesso))
        .replace("__N_ADATTI__",   str(adatti))
        .replace("__CHIP_AI_N__",  chip_ai_n)
        .replace("__COUNT__",      str(totale))
        .replace("__NSOURCES__",   str(n_fonti))
        .replace("__SOURCELIST__", _e(elenco_fonti))
        .replace("__CAT_CHIPS__",  _chips_categorie(conteggi))
        .replace("__CARDS__",      cards)
        .replace("__EMPTY_SUB__",  empty_sub)
    )

    if not jobs:
        pagina = pagina.replace('<div class="empty" id="empty">',
                                '<div class="empty show" id="empty">')

    Path(output_path).write_text(pagina, encoding="utf-8")
    print(f"[OK] Dashboard generata: {output_path} ({totale} annunci)")
