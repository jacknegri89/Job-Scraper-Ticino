"""
Generate the interactive ``index.html`` job dashboard.

Design: a road-sign header, a filter rail (search, sort, categories, AI match)
and one ticket-style row per job. Each row shows the distance from the home
city configured in ``user_config.py`` as a small route ruler. Light and dark
themes follow the system setting.

File layout:
  - presentation constants (CATEGORY, SOURCE_LABEL)
  - raw description cleanup (_clean_raw)
  - card helpers, one named function per HTML block
  - build_card: assemble one job card
  - generate_html: compute dashboard stats and fill the page template
"""

import html as html_lib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from distance_calculator import HOME_CITY, is_home_configured, km_from_home
from salary_calculator import calculate_net_salary
from ai_analyzer import AI_DESCRIPTION, AI_GROSS_SALARY, AI_REASON, AI_SUITABLE, normalize_ai_fields

Job = dict[str, Any]
CategoryInfo = tuple[str, str]

# category_id: (dot_color, dashboard_label). IDs come from job_filter.py.
CATEGORY: dict[str, CategoryInfo] = {
    "tech":         ("#2B63B8", "Tech / IT"),
    "logistics":    ("#2E8B57", "Logistics"),
    "production":   ("#0F8A94", "Manufacturing"),
    "food_service": ("#C23B78", "Food service"),
    "cleaning":     ("#B58100", "Cleaning"),
    "retail":       ("#D2641E", "Retail"),
    "transport":    ("#6C52C4", "Transport"),
    "other":        ("#7B858E", "Other"),
}

# The route ruler on each card spans this many km; one tick is drawn every TICK km.
ROUTE_MAX_KM = 30
ROUTE_TICK_KM = 5

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
        '<p class="sal-note">Indicative estimate &middot; cross-border regime after 2023-07-17</p>',
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
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}", email):
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
    main_column = [
        '<div class="card-main">', _card_header(view), _card_title(job),
        _description_block(job), view["ai_html"], "</div>",
    ]
    side_column = [
        '<div class="card-side">', _card_meta(job, view), _route_block(view),
        _salary_block(job), _email_block(job), _apply_link(job), "</div>",
    ]
    return "\n".join([_card_open(job, view), *main_column, *side_column, "</article>"])


def _route_block(view: dict[str, Any]) -> str:
    """Small ruler from the home city (left) to the job town (red pin)."""
    km = view["km"]
    if km is None:
        return ""
    position_percent = min(km / ROUTE_MAX_KM, 1) * 100
    tick_percent = ROUTE_TICK_KM / ROUTE_MAX_KM * 100
    home_city_label = _escape_html(HOME_CITY)
    return (
        '<div class="route" aria-hidden="true">'
        f'<div class="route-line" style="--at:{position_percent:.1f}%;--km-step:{tick_percent:.2f}%"></div>'
        f'<div class="route-ends"><span>{home_city_label}</span><span>{ROUTE_MAX_KM} km</span></div>'
        "</div>"
    )


def _card_open(job: Job, view: dict[str, Any]) -> str:
    return (
        f'<article class="card" data-category="{_escape_html(view["category_id"])}" '
        f'data-ai="{view["ai_filter"]}" data-km="{view["km_attr"]}" '
        f'data-search="{_search_blob(job)}" style="--accent:{view["color"]}">'
    )


def _card_header(view: dict[str, Any]) -> str:
    return (
        '<div class="card-head">'
        f'<span class="card-cat">{view["category_label"]}</span>'
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
    rows = [_meta_row("Location", _escape_html(job.get("city", "")))]
    if is_home_configured():
        rows.append(_meta_row(f"From {home_city_label}", _distance_label(view["km"])))
    rows.append(_meta_row("Posted", _escape_html(job.get("date", "")) or "-"))
    return rows


def _meta_row(label: str, value: str) -> str:
    return f'<div><span class="meta-k">{label}</span><span class="meta-v">{value}</span></div>'


def _apply_link(job: Job) -> str:
    return f'<a class="apply-btn" href="{_safe_url(job)}" target="_blank" rel="noopener noreferrer">View listing <span class="arrow">&rarr;</span></a>'


# ----------------------------------------------------------------
# Page template
# ----------------------------------------------------------------

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<title>Ticino Jobs - cross-border dashboard</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%230B3D91%22/><path d=%22M14 32h34M37 20l12 12-12 12%22 fill=%22none%22 stroke=%22%23fff%22 stroke-width=%226%22 stroke-linejoin=%22round%22/></svg>">
<style>
/* Palette: cold stone paper, ink, Ticino blue for the header, Ticino red for the one action. */
:root {
  --paper:  #E8EBE9;
  --card:   #FBFBF9;
  --card-2: #F1F3F1;
  --ink:    #18212B;
  --ink-2:  #46515C;
  --ink-3:  #63707B;
  --rule:   #CBD1D3;
  --rule-2: #98A2A8;
  --blue:   #0B3D91;
  --red:    #C8102E;
  --red-hi: #A50D26;
  --ok:     #1B6B47;
  --ok-bg:  #E0EFE6;
  --no-bg:  #EEF0EF;
  --focus:  #0B63E5;
  --sans:   "Bahnschrift", "DIN Alternate", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  --mono:   ui-monospace, "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:  #10161B;
    --card:   #182027;
    --card-2: #1F2831;
    --ink:    #E8ECEF;
    --ink-2:  #B2BCC4;
    --ink-3:  #8E9AA4;
    --rule:   #2C3640;
    --rule-2: #4C5963;
    --blue:   #123F8C;
    --ok:     #67C795;
    --ok-bg:  #17301F;
    --no-bg:  #1C242B;
    --focus:  #7DB2FF;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
body {
  background: var(--paper); color: var(--ink);
  font-family: var(--sans); font-size: 14.5px; line-height: 1.5;
}
[hidden] { display: none !important; }

/* Header: a road sign for the Mendrisiotto */
.sign { background: var(--blue); color: #fff; }
.sign-in {
  max-width: 1240px; margin: 0 auto; padding: 30px 24px 26px;
  display: grid; gap: 14px;
}
.sign-top { display: flex; justify-content: space-between; align-items: baseline;
            flex-wrap: wrap; gap: 6px 24px; }
h1 {
  font-size: 40px; font-weight: 700; line-height: 1; letter-spacing: .01em;
  text-transform: uppercase; font-stretch: 75%;
}
h1 .to { display: inline-block; margin-left: 10px; color: #fff; opacity: .7; }
.updated { font-family: var(--mono); font-size: 12px; opacity: .8; }
.subtitle { max-width: 62ch; opacity: .88; }
.tally { display: flex; flex-wrap: wrap; gap: 6px 28px; padding-top: 14px;
         border-top: 1px solid rgba(255,255,255,.35); }
.tally-item { display: flex; align-items: baseline; gap: 8px; }
.tally-item b { font-family: var(--mono); font-size: 20px; font-weight: 600;
                font-variant-numeric: tabular-nums; }
.tally-item span { font-size: 12.5px; opacity: .8; text-transform: uppercase; letter-spacing: .06em; }
.sign::after { content: ""; display: block; height: 5px; background: var(--red); }

/* Page: filter rail on the left, listings on the right */
.page {
  max-width: 1240px; margin: 0 auto; padding: 28px 24px 80px;
  display: grid; grid-template-columns: 232px minmax(0, 1fr); gap: 36px; align-items: start;
}
.rail { position: sticky; top: 16px; display: grid; gap: 18px; }
.field-label { display: block; margin-bottom: 6px; font-size: 11px; font-weight: 700;
               text-transform: uppercase; letter-spacing: .09em; color: var(--ink-3); }
#search, #sort {
  width: 100%; background: var(--card); color: var(--ink);
  border: 1px solid var(--rule-2); border-radius: 3px;
  padding: 9px 11px; font: inherit; font-size: 14px;
}
#search::placeholder { color: var(--ink-3); }
#search:focus { border-color: var(--ink); }
.found { font-size: 13px; color: var(--ink-2); }
.found b { font-family: var(--mono); color: var(--ink); font-variant-numeric: tabular-nums; }

.chips { display: grid; gap: 2px; }
.chip {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  background: transparent; color: var(--ink-2); font: inherit; font-size: 14px;
  border: 0; border-left: 3px solid transparent; border-radius: 0;
  padding: 7px 10px; cursor: pointer;
}
.chip:hover { background: var(--card-2); color: var(--ink); }
.chip[aria-pressed="true"] { border-left-color: var(--ink); background: var(--card);
                             color: var(--ink); font-weight: 700; }
.chip .n { margin-left: auto; font-family: var(--mono); font-size: 12px; color: var(--ink-3);
           font-variant-numeric: tabular-nums; }
.chip-dot { width: 9px; height: 9px; background: var(--chip-accent, var(--ink-3)); flex: none; }
.chip-ai { margin-top: 8px; border: 1px solid var(--ok); color: var(--ok); border-radius: 3px;
           border-left-width: 3px; font-weight: 600; }
.chip-ai:hover { background: var(--ok-bg); color: var(--ok); }
.chip-ai[aria-pressed="true"] { background: var(--ok); color: var(--card); border-color: var(--ok); }
.chip-ai[aria-pressed="true"] .n { color: var(--card); }

/* Listings */
.list { display: grid; gap: 12px; }
.card {
  --accent: var(--ink-3);
  display: grid; grid-template-columns: minmax(0, 1fr) 292px;
  background: var(--card); border: 1px solid var(--rule);
  border-left: 5px solid var(--accent); border-radius: 3px;
}
.card:hover { border-color: var(--rule-2); border-left-color: var(--accent); }
.card-main { padding: 20px 24px 22px; display: grid; gap: 12px; align-content: start; min-width: 0; }
.card-side {
  padding: 20px; display: flex; flex-direction: column; gap: 16px;
  border-left: 2px dashed var(--rule); background: var(--card-2);
}
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.card-cat { font-size: 11.5px; font-weight: 700; color: var(--ink-2);
            text-transform: uppercase; letter-spacing: .08em; }
.card-source { font-family: var(--mono); font-size: 11.5px; color: var(--ink-3); }
.card-title { font-size: 21px; font-weight: 700; line-height: 1.2; letter-spacing: -.005em; }
.card-company { color: var(--ink-2); margin-top: -6px; }
.card-desc { color: var(--ink-2); max-width: 72ch; line-height: 1.6; }

.ai { display: flex; gap: 10px; align-items: flex-start; }
.ai-ico { flex: none; width: 20px; height: 20px; margin-top: 1px; border-radius: 50%;
          display: grid; place-items: center; font-size: 11px; font-weight: 700;
          background: var(--ok); color: var(--card); }
.ai-no .ai-ico { background: var(--ink-3); }
.ai-tag { font-weight: 700; font-size: 13px; color: var(--ok); }
.ai-no .ai-tag { color: var(--ink-3); }
.ai-why { font-size: 13px; color: var(--ink-2); margin-top: 2px; max-width: 66ch; }

/* Side column: facts, route ruler, pay, action */
.card-meta { display: grid; gap: 0; }
.card-meta > div { display: flex; justify-content: space-between; gap: 12px;
                   padding: 6px 0; border-bottom: 1px dotted var(--rule-2); }
.meta-k { font-size: 12px; color: var(--ink-3); }
.meta-v { font-family: var(--mono); font-size: 13px; font-weight: 600; text-align: right;
          font-variant-numeric: tabular-nums; }
.route { display: grid; gap: 4px; }
.route-line {
  position: relative; height: 12px;
  border-bottom: 2px solid var(--ink);
  background: repeating-linear-gradient(90deg, var(--rule-2) 0 1px, transparent 1px var(--km-step));
  background-size: 100% 6px; background-repeat: no-repeat; background-position: bottom;
}
.route-line::after {
  content: ""; position: absolute; bottom: -6px; left: var(--at); width: 10px; height: 10px;
  margin-left: -5px; background: var(--red); border: 2px solid var(--card-2); border-radius: 50%;
  box-sizing: content-box;
}
.route-ends { display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-3); }

.salary { font-size: 12.5px; display: grid; gap: 4px;
          background: var(--card); border: 1px solid var(--rule); padding: 10px 12px; }
.sal-head { font-family: var(--sans); font-size: 11px; font-weight: 700; text-transform: uppercase;
            letter-spacing: .09em; color: var(--ink-3); padding-bottom: 4px; }
.sal-row { display: flex; justify-content: space-between; gap: 10px; color: var(--ink-2); }
.sal-num { font-family: var(--mono); color: var(--ink); font-variant-numeric: tabular-nums; white-space: nowrap; }
.sal-row.deduct .sal-num { color: var(--ink-2); }
.sal-net { display: flex; justify-content: space-between; gap: 10px; margin-top: 4px;
           padding: 7px 8px; background: var(--ink); color: var(--card);
           font-size: 13px; font-weight: 700; }
.sal-net span:last-child { font-family: var(--mono); white-space: nowrap; }
.sal-note { font-family: var(--sans); font-size: 11px; color: var(--ink-3); line-height: 1.35; }

.email-link { font-size: 13px; color: var(--ink-2); word-break: break-all; }
.email-link:hover { color: var(--ink); }

.apply-btn {
  margin-top: auto; display: flex; justify-content: space-between; align-items: center;
  background: var(--red); color: #fff; text-decoration: none;
  font-weight: 700; font-size: 14px; padding: 11px 14px; border-radius: 3px;
}
.apply-btn:hover { background: var(--red-hi); }
.apply-btn .arrow { transition: transform .15s; }
.apply-btn:hover .arrow { transform: translateX(3px); }

.empty { display: none; padding: 56px 0; color: var(--ink-2); }
.empty.show { display: block; }
.empty h3 { font-size: 22px; font-weight: 700; color: var(--ink); margin-bottom: 6px; }

footer {
  max-width: 1240px; margin: 0 auto; padding: 22px 24px 44px;
  border-top: 1px solid var(--rule); color: var(--ink-3); font-size: 12.5px; line-height: 1.8;
}

@media (max-width: 900px) {
  .page { grid-template-columns: 1fr; gap: 20px; padding-top: 20px; }
  .rail { position: static; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { width: auto; border: 1px solid var(--rule-2); border-radius: 999px; padding: 6px 12px; }
  .chip[aria-pressed="true"] { border-color: var(--ink); }
  .chip-ai { margin-top: 0; }
  h1 { font-size: 32px; }
}
@media (max-width: 720px) {
  .card { grid-template-columns: 1fr; }
  .card-side { border-left: 0; border-top: 2px dashed var(--rule); }
  .card-main { padding: 18px 18px 20px; }
}
@media (prefers-reduced-motion: reduce) {
  .apply-btn .arrow { transition: none; }
}
</style>
</head>
<body>

<header class="sign">
  <div class="sign-in">
    <div class="sign-top">
      <h1>Ticino Jobs<span class="to">&rarr; Mendrisiotto</span></h1>
      <span class="updated">Updated __NOW__</span>
    </div>
    <p class="subtitle">Listings from __NSOURCES__ Swiss portals, filtered for the
       Mendrisio district.__DISTANCE_NOTE__</p>
    <div class="tally">
      <div class="tally-item"><b>__COUNT__</b><span>cached jobs</span></div>
      __MATCH_TALLY__
      <div class="tally-item"><b>__NSOURCES__</b><span>sources</span></div>
    </div>
  </div>
</header>

<div class="page">
  <aside class="rail" aria-label="Filters">
    <div>
      <label class="field-label" for="search">Search</label>
      <input id="search" type="search" placeholder="Title, company or city" autocomplete="off">
    </div>
    <div>
      <label class="field-label" for="sort">Sort by</label>
      <select id="sort">
        <option value="date">Newest</option>
        __NEAREST_OPTION__
      </select>
    </div>
    <p class="found" aria-live="polite"><b id="visible-n">__COUNT__</b> results</p>
    <div>
      <span class="field-label" id="field-label">Field</span>
      <div class="chips" role="group" aria-labelledby="field-label">
        <button class="chip" data-cat="all" aria-pressed="true">All <span class="n">__COUNT__</span></button>
        __CAT_CHIPS__
        __CHIP_AI__
      </div>
    </div>
  </aside>

  <main>
    <div class="list" id="grid">
__CARDS__
    </div>
    <div class="empty" id="empty">
      <h3>No jobs match</h3>
      <p>__EMPTY_SUB__</p>
    </div>
  </main>
</div>

<footer>
  Sources: __SOURCELIST__<br>
  Salary and distance figures are indicative estimates, not offers.
</footer>

<script>
"use strict";

const state = { category: "all", aiOnly: false, query: "" };
const grid = document.getElementById("grid");
const cards = Array.from(grid.querySelectorAll(".card"));
const chips = Array.from(document.querySelectorAll(".chip"));

// Original order means newest first, as sorted by the generator.
cards.forEach((card, index) => { card.dataset.order = index; });

function cardMatches(card) {
  const okCategory = state.category === "all" || card.dataset.category === state.category;
  const okAI = !state.aiOnly || card.dataset.ai === "match";
  const okQuery = !state.query || card.dataset.search.includes(state.query);
  return okCategory && okAI && okQuery;
}

function applyFilters() {
  let visible = 0;
  for (const card of cards) {
    const show = cardMatches(card);
    card.hidden = !show;
    if (show) {
      visible++;
    }
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
  for (const card of sorted) {
    grid.appendChild(card);
  }
}

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value.toLowerCase().trim();
  applyFilters();
});

document.getElementById("sort").addEventListener("change", (event) => {
  applySort(event.target.value);
});

// Category and AI chips share one delegated listener.
document.querySelector(".chips").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) {
    return;
  }
  if (chip.id === "chip-ai") {
    state.aiOnly = !state.aiOnly;
    chip.setAttribute("aria-pressed", String(state.aiOnly));
  } else {
    state.category = chip.dataset.cat;
    for (const button of chips) {
      if (button.dataset.cat) {
        button.setAttribute("aria-pressed", String(button === chip));
      }
    }
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
            f'<button class="chip" data-cat="{category_id}" aria-pressed="false" style="--chip-accent:{color}">'
            f'<span class="chip-dot"></span>{label} <span class="n">{count}</span></button>'
        )
    return "\n      ".join(chips)


def _source_list(jobs: list[Job]) -> tuple[int, str]:
    """Return the number of sources and a readable source list actually present."""
    present_sources = {str(job.get("source")) for job in jobs if job.get("source")}
    if not present_sources:
        return 0, "-"
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
    has_ai_results = any(job.get(AI_SUITABLE) is not None for job in jobs)
    counts = _count_by_category(jobs)
    source_count, source_names = _source_list(jobs)
    return {
        "__NOW__": _escape_html(datetime.now().strftime("%Y-%m-%d - %H:%M")),
        "__MATCH_TALLY__": _match_tally(matches, has_ai_results),
        "__CHIP_AI__": _ai_chip(matches, has_ai_results), "__COUNT__": str(len(jobs)),
        "__NSOURCES__": str(source_count), "__SOURCELIST__": _escape_html(source_names),
        "__CAT_CHIPS__": _category_chips(counts),
        "__DISTANCE_NOTE__": _distance_note(), "__NEAREST_OPTION__": _nearest_option(),
        "__CARDS__": "\n".join(build_card(job) for job in jobs),
        "__EMPTY_SUB__": _empty_subtitle(jobs),
    }


def _distance_note() -> str:
    if not is_home_configured():
        return ""
    return f" Distances are straight-line estimates from {_escape_html(HOME_CITY)}."


def _nearest_option() -> str:
    if not is_home_configured():
        return ""
    return '<option value="km">Nearest</option>'


def _match_tally(matches: int, has_ai_results: bool) -> str:
    """Show the match count only when the AI has judged at least one job."""
    if not has_ai_results:
        return ""
    return f'<div class="tally-item"><b>{matches}</b><span>good matches</span></div>'


def _ai_chip(matches: int, has_ai_results: bool) -> str:
    """The "Good matches" filter makes no sense without AI results, so it is hidden."""
    if not has_ai_results:
        return ""
    return (
        '<button class="chip chip-ai" id="chip-ai" aria-pressed="false">'
        f'&#10003; Good matches <span class="n">{matches}</span></button>'
    )


def _empty_subtitle(jobs: list[Job]) -> str:
    if jobs:
        return "Try changing the filters or search text."
    return "No cached jobs yet: run python main.py"


def _fill_template(replacements: dict[str, str]) -> str:
    # One pass over the template: text inserted by a marker is never scanned again,
    # so a job title that contains "__COUNT__" cannot be rewritten by a later marker.
    def replace_marker(match: re.Match) -> str:
        return replacements.get(match.group(0), match.group(0))

    return re.sub(r"__[A-Z_]+__", replace_marker, _TEMPLATE)


def _show_empty_state(page: str) -> str:
    return page.replace('<div class="empty" id="empty">', '<div class="empty show" id="empty">')
