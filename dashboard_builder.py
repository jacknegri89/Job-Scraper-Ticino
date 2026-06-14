"""
Generate the interactive ``index.html`` job dashboard.

Design: a readable dark theme with search, category chips, an AI match filter,
sorting, and a responsive card grid. Each card also shows the distance from the
home city configured in ``user_config.py``.

File layout:
  - presentation constants (CATEGORY, SOURCE_LABEL)
  - raw description cleanup (_clean_raw)
  - card helpers, one named function per HTML block
  - build_card: assemble one job card
  - generate_html: compute dashboard stats and fill the page template
"""

import html as html_lib
from datetime import datetime
from pathlib import Path
from typing import Any

from distance_calculator import HOME_CITY, km_from_home
from salary_calculator import calculate_net_salary
from ai_analyzer import AI_DESCRIPTION, AI_GROSS_SALARY, AI_REASON, AI_SUITABLE, normalize_ai_fields

Job = dict[str, Any]
CategoryInfo = tuple[str, str]

# category_id: (dot_color, dashboard_label). IDs come from job_filter.py.
CATEGORY: dict[str, CategoryInfo] = {
    "tech":         ("#79B8FF", "Tech / IT"),
    "logistics":    ("#7EE2A8", "Logistics"),
    "production":   ("#76E3EA", "Manufacturing"),
    "food_service": ("#FF9EC1", "Food service"),
    "cleaning":     ("#FFD47E", "Cleaning"),
    "retail":       ("#FFB07C", "Retail"),
    "transport":    ("#BFA9FF", "Transport"),
    "other":        ("#9AA0A6", "Other"),
}

SOURCE_LABEL: dict[str, str] = {
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
    "frontaliereticino.ch": "frontaliereticino.ch",
    "linkedin.ch":          "LinkedIn",
}


def _escape_html(value: object) -> str:
    """Escape a value before it is inserted into HTML."""
    return html_lib.escape(str(value))


# ----------------------------------------------------------------
# Raw description cleanup
# ----------------------------------------------------------------

# Safe substrings that appear only in portal navigation or boilerplate text.
_JUNK = frozenset([
    "home / offerte di lavoro", "candidati ora", "inserisci la tua email",
    "dettagli offerta di lavoro", "dettagli dell'annuncio",
    "log in,", "save apply", "per candidarti",
    "mostra offerte simili", "imposta un job alert",
    "prodotti metallurgici", "elettronica e semiconduttori",
    "edilizia e costruzioni", "gestione progetti", "electrics",
    "classe e stipendio annuo", "sede di lavoro:", "tipo di lavoro:",
])

# Ambiguous terms remove a segment only when they appear at the start.
_JUNK_PREFIX = (
    "registrati", "login", "opportunit", "inserisci la tua",
    "dettagli dell", "offerta:", "soggetto:",
)

# Label prefixes removed from the start of a description segment.
_LABEL_PREFIX = ("descrizione:", "dettagli:", "offerta di lavoro:", "soggetto:")


def _strip_label_prefix(segment: str) -> str:
    """Remove a known scraped label prefix from a segment."""
    lowered = segment.lower()
    for label in _LABEL_PREFIX:
        if lowered.startswith(label):
            return segment[len(label):].strip()
    return segment


def _is_junk(segment: str) -> bool:
    lowered = segment.lower()
    if len(segment) < 20:
        return True
    if any(junk in lowered for junk in _JUNK):
        return True
    return lowered.startswith(_JUNK_PREFIX)


def _clean_raw(text: str) -> str:
    """Remove breadcrumbs, buttons, and form metadata from scraped text."""
    segments = [part.strip() for part in text.split(" | ") if part.strip()]
    useful_segments: list[str] = []
    for segment in segments:
        segment = _strip_label_prefix(segment)
        if not _is_junk(segment):
            useful_segments.append(segment)
    return " ".join(useful_segments)


# ----------------------------------------------------------------
# Card blocks, one function per block
# ----------------------------------------------------------------

def _description_html(job: Job) -> str:
    """Prefer the AI description, then fall back to cleaned raw text."""
    normalize_ai_fields(job)
    ai_description = str(job.get(AI_DESCRIPTION) or "").strip()
    if ai_description:
        return _escape_html(ai_description).replace("\n", "<br>")

    raw_description = str(job.get("description") or "").strip()
    if not raw_description:
        return ""
    cleaned = _clean_raw(raw_description)
    if not cleaned:
        return ""
    truncated = cleaned[:700] + ("..." if len(cleaned) > 700 else "")
    return _escape_html(truncated)


def _description_block(job: Job) -> str:
    body = _description_html(job)
    if not body:
        return ""
    return f'<p class="card-desc">{body}</p>'


def _ai_block(job: Job) -> tuple[str, str]:
    """Return the data-ai value and the visible AI verdict block."""
    normalize_ai_fields(job)
    is_match = job.get(AI_SUITABLE)
    reason_html = _ai_reason_html(job)
    if is_match is True:
        return _ai_result("match", "ai-ok", "&#10003;", "Good match", reason_html)
    if is_match is False:
        return _ai_result("not_match", "ai-no", "&#10005;", "Not a match", reason_html)
    return "none", ""


def _ai_reason_html(job: Job) -> str:
    reason = _escape_html(job.get(AI_REASON, ""))
    return f'<p class="ai-why">{reason}</p>' if reason else ""


def _ai_result(filter_value: str, css_class: str, icon: str, label: str, reason_html: str) -> tuple[str, str]:
    return filter_value, _ai_html(css_class, icon, label, reason_html)


def _ai_html(css_class: str, icon: str, label: str, reason_html: str) -> str:
    return (
        f'<div class="ai {css_class}"><span class="ai-ico">{icon}</span><div>'
        f'<span class="ai-tag">{label}</span>{reason_html}</div></div>'
    )


def _salary_block(job: Job) -> str:
    """Build the salary panel: Swiss gross pay to estimated Italian net pay."""
    normalize_ai_fields(job)
    net_salary = _net_salary(job)
    if not net_salary:
        return ""
    return _salary_panel(net_salary)


def _net_salary(job: Job) -> dict[str, int]:
    gross_salary = job.get(AI_GROSS_SALARY)
    if not gross_salary:
        return {}
    return calculate_net_salary(gross_salary)


def _salary_panel(net_salary: dict[str, int]) -> str:
    rows = [
        '<div class="salary">'
        '<div class="sal-head">Estimated salary</div>',
        _salary_row("Swiss gross", f'{net_salary["gross_chf"]:,} CHF'),
        _salary_row("Swiss social contributions", f'{net_salary["social_chf"]:,} CHF', deduct=True),
        _salary_row("Ticino withholding tax", f'{net_salary["withholding_chf"]:,} CHF', deduct=True),
        _salary_row("Additional Italian income tax", f'{net_salary["extra_italian_tax_eur"]:,} &euro;', deduct=True),
        _salary_net_row(net_salary["net_eur"]),
        '<p class="sal-note">Estimate &plusmn;15% &middot; cross-border regime after 2023-07-17</p>',
        "</div>",
    ]
    return "".join(rows)


def _salary_row(label: str, value: str, deduct: bool = False) -> str:
    row_class = "sal-row deduct" if deduct else "sal-row"
    prefix = "&minus;" if deduct else ""
    return f'<div class="{row_class}"><span>{label}</span><span class="sal-num">{prefix}{value}</span></div>'


def _salary_net_row(net_eur: int) -> str:
    return f'<div class="sal-net"><span>Net in Italy</span><span>~{net_eur:,} &euro;/month</span></div>'


def _email_block(job: Job) -> str:
    email = str(job.get("email") or "").strip()
    if not email:
        return ""
    escaped_email = _escape_html(email)
    return f'<a class="email-link" href="mailto:{escaped_email}">&#9993; {escaped_email}</a>'


def _distance_of(job: Job) -> float | None:
    return km_from_home(str(job.get("city") or ""))


def _distance_label(km: float | None) -> str:
    if km is None:
        return "-"
    return f"{km:.0f} km"


def _safe_url(job: Job) -> str:
    url = str(job.get("url") or "")
    if url.startswith(("https://", "http://")):
        return _escape_html(url)
    return "#"


def _search_blob(job: Job) -> str:
    """Lowercase text used by the live search box."""
    fields = (str(job.get("title") or ""), str(job.get("company") or ""),
              str(job.get("city") or ""), str(job.get("email") or ""))
    return _escape_html(" ".join(fields).lower())


# ----------------------------------------------------------------
# Full card
# ----------------------------------------------------------------

def build_card(job: Job) -> str:
    view = _card_view(job)
    return _card_html(job, view)


def _card_view(job: Job) -> dict[str, Any]:
    category_id = str(job.get("category") or "other")
    color, category_label = CATEGORY.get(category_id, CATEGORY["other"])
    source_id = str(job.get("source") or "")
    km = _distance_of(job)
    ai_filter, ai_html = _ai_block(job)
    return {
        "category_id": category_id, "color": color, "category_label": category_label,
        "source": SOURCE_LABEL.get(source_id, _escape_html(source_id)),
        "km": km, "km_attr": f"{km:.1f}" if km is not None else "9999",
        "ai_filter": ai_filter, "ai_html": ai_html,
    }


def _card_html(job: Job, view: dict[str, Any]) -> str:
    return "\n".join([
        _card_open(job, view), _card_header(view), _card_title(job),
        _description_block(job), view["ai_html"], _card_meta(job, view),
        _salary_block(job), _email_block(job), _apply_link(job), "</article>",
    ])


def _card_open(job: Job, view: dict[str, Any]) -> str:
    return (
        f'<article class="card" data-category="{_escape_html(view["category_id"])}" '
        f'data-ai="{view["ai_filter"]}" data-km="{view["km_attr"]}" '
        f'data-search="{_search_blob(job)}" style="--accent:{view["color"]}">'
    )


def _card_header(view: dict[str, Any]) -> str:
    return (
        '<div class="card-head">'
        f'<span class="card-cat"><span class="cat-dot"></span>{view["category_label"]}</span>'
        f'<span class="card-source">{view["source"]}</span></div>'
    )


def _card_title(job: Job) -> str:
    title = _escape_html(job.get("title", ""))
    company = _escape_html(job.get("company", "")) or "&nbsp;"
    return f'<h2 class="card-title">{title}</h2><p class="card-company">{company}</p>'


def _card_meta(job: Job, view: dict[str, Any]) -> str:
    return '<div class="card-meta">' + "".join(_card_meta_rows(job, view)) + "</div>"


def _card_meta_rows(job: Job, view: dict[str, Any]) -> list[str]:
    home_city_label = _escape_html(HOME_CITY)
    return [
        _meta_row("Location", _escape_html(job.get("city", ""))),
        _meta_row(f"From {home_city_label}", _distance_label(view["km"])),
        _meta_row("Posted", _escape_html(job.get("date", "")) or "-"),
    ]


def _meta_row(label: str, value: str) -> str:
    return f'<div><span class="meta-k">{label}</span><span class="meta-v">{value}</span></div>'


def _apply_link(job: Job) -> str:
    return f'<a class="apply-btn" href="{_safe_url(job)}" target="_blank" rel="noopener noreferrer">Apply <span class="arrow">&rarr;</span></a>'


# ----------------------------------------------------------------
# Page template
# ----------------------------------------------------------------

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ticino Jobs - cross-border dashboard</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2214%22 fill=%22%23161B22%22/><circle cx=%2232%22 cy=%2232%22 r=%2210%22 fill=%22%233FB950%22/></svg>">
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

/* Header */
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

/* Toolbar */
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

/* Card grid */
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
.card[data-ai="not_match"] { opacity: .45; }
.card[data-ai="not_match"]:hover { opacity: 1; }

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

/* Empty state and footer */
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
    <h1><span class="dot">&bull;</span> Ticino Jobs</h1>
    <span class="updated">Last updated __NOW__</span>
  </div>
  <p class="subtitle">Jobs from __NSOURCES__ Swiss portals, filtered for the
     Mendrisio district. Distances are calculated from __HOME_CITY__ as straight-line estimates.</p>
  <div class="stats">
    <div class="stat"><b>__COUNT__</b><span>active jobs</span></div>
    <div class="stat green"><b>__N_MATCHES__</b><span>good matches</span></div>
    <div class="stat"><b>__NSOURCES__</b><span>sources</span></div>
  </div>
</header>

<div class="toolbar">
  <div class="toolbar-in">
    <div class="row1">
      <input id="search" type="text" placeholder="Search title, company, or city...">
      <select id="sort">
        <option value="date">Newest</option>
        <option value="km">Nearest</option>
      </select>
      <span class="count"><b id="visible-n">__COUNT__</b> results</span>
    </div>
    <div class="chips">
      <button class="chip active" data-cat="all">All <span class="n">__COUNT__</span></button>
      __CAT_CHIPS__
      <button class="chip chip-ai" id="chip-ai">&#10003; Good matches__CHIP_AI_N__</button>
    </div>
  </div>
</div>

<main>
  <div class="grid" id="grid">
__CARDS__
  </div>
  <div class="empty" id="empty">
    <h3>No results</h3>
    <p>__EMPTY_SUB__</p>
  </div>
</main>

<footer>
  Sources: __SOURCELIST__<br>
  Cross-border dashboard &middot; salary and distance figures are indicative estimates
</footer>

<script>
"use strict";

const state = { category: "all", aiOnly: false, query: "" };
const grid  = document.getElementById("grid");
const cards = Array.from(grid.querySelectorAll(".card"));

// Original order means newest first, as sorted by the generator.
cards.forEach((card, index) => { card.dataset.order = index; });

function applyFilters() {
  let visible = 0;
  for (const card of cards) {
    const okCategory = state.category === "all" || card.dataset.category === state.category;
    const okAI = !state.aiOnly || card.dataset.ai === "match";
    const okQuery = !state.query || card.dataset.search.includes(state.query);
    const show = okCategory && okAI && okQuery;
    card.style.display = show ? "" : "none";
    if (show) visible++;
  }
  document.getElementById("visible-n").textContent = visible;
  document.getElementById("empty").classList.toggle("show", visible === 0);
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

// Live search.
document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value.toLowerCase().trim();
  applyFilters();
});

// Sorting.
document.getElementById("sort").addEventListener("change", (event) => {
  applySort(event.target.value);
});

// Category and AI chips use one delegated listener.
document.querySelector(".chips").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;

  if (chip.id === "chip-ai") {
    state.aiOnly = !state.aiOnly;
    chip.classList.toggle("active", state.aiOnly);
  } else {
    state.category = chip.dataset.cat;
    document.querySelectorAll(".chip[data-cat]").forEach(button => button.classList.remove("active"));
    chip.classList.add("active");
  }
  applyFilters();
});

// Press "/" to focus search.
addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement.tagName !== "INPUT") {
    event.preventDefault();
    document.getElementById("search").focus();
  }
});
</script>

</body>
</html>
"""


# ----------------------------------------------------------------
# Page generation
# ----------------------------------------------------------------

def _count_by_category(jobs: list[Job]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        category_id = str(job.get("category") or "other")
        counts[category_id] = counts.get(category_id, 0) + 1
    return counts


def _category_chips(counts: dict[str, int]) -> str:
    """Build one chip button for each category present in the current jobs."""
    chips: list[str] = []
    for category_id, (color, label) in CATEGORY.items():
        count = counts.get(category_id, 0)
        if count == 0:
            continue
        chips.append(
            f'<button class="chip" data-cat="{category_id}" style="--chip-accent:{color}">'
            f'<span class="chip-dot"></span>{label} <span class="n">{count}</span></button>'
        )
    return "\n      ".join(chips)


def _source_list(jobs: list[Job]) -> tuple[int, str]:
    """Return the number of sources and a readable source list actually present."""
    present_sources = {str(job.get("source")) for job in jobs if job.get("source")}
    if not present_sources:
        return len(SOURCE_LABEL), " | ".join(SOURCE_LABEL.values())
    names = sorted(SOURCE_LABEL.get(source, source) for source in present_sources)
    return len(present_sources), " | ".join(names)


def generate_html(jobs: list[Job], output_path: str | Path = "index.html") -> None:
    jobs = [normalize_ai_fields(job) for job in jobs]
    page = _dashboard_page(jobs)
    Path(output_path).write_text(page, encoding="utf-8")
    print(f"[OK] Dashboard generated: {output_path} ({len(jobs)} jobs)")


def _dashboard_page(jobs: list[Job]) -> str:
    page = _fill_template(_template_replacements(jobs))
    if not jobs:
        return _show_empty_state(page)
    return page


def _template_replacements(jobs: list[Job]) -> dict[str, str]:
    matches = sum(1 for job in jobs if job.get(AI_SUITABLE) is True)
    counts = _count_by_category(jobs)
    source_count, source_names = _source_list(jobs)
    return {
        "__NOW__": _escape_html(datetime.now().strftime("%Y-%m-%d - %H:%M")), "__N_MATCHES__": str(matches),
        "__CHIP_AI_N__": _ai_chip_count(matches), "__COUNT__": str(len(jobs)),
        "__NSOURCES__": str(source_count), "__SOURCELIST__": _escape_html(source_names),
        "__CAT_CHIPS__": _category_chips(counts), "__HOME_CITY__": _escape_html(HOME_CITY),
        "__CARDS__": "\n".join(build_card(job) for job in jobs),
        "__EMPTY_SUB__": _empty_subtitle(jobs),
    }


def _ai_chip_count(matches: int) -> str:
    return f' <span class="n">{matches}</span>' if matches else ""


def _empty_subtitle(jobs: list[Job]) -> str:
    if jobs:
        return "Try changing the filters or search text."
    return "No cached jobs yet: run python main.py"


def _fill_template(replacements: dict[str, str]) -> str:
    page = _TEMPLATE
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page


def _show_empty_state(page: str) -> str:
    return page.replace('<div class="empty" id="empty">', '<div class="empty show" id="empty">')
