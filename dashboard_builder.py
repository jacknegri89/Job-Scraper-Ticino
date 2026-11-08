"""
Generate the interactive ``index.html`` job dashboard.

Design: a road-sign header, a filter rail (search, sort, field, country, seniority,
freshness, salary) and one ticket-style row per job. Each row shows where the job is
and how sure we are, which portal it comes from, when it was published and last
checked, the salary that is written in the listing or estimated (with its origin and
assumptions) and the distance from home as a small route ruler. Light and dark themes
follow the system setting. Nothing is loaded from the internet.

File layout:
  - presentation constants (CATEGORY, SOURCE_LABEL, label tables)
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

from ai_analyzer import AI_DESCRIPTION, AI_REASON, AI_SUITABLE, normalize_ai_fields
from distance_calculator import HOME_CITY, is_home_configured, km_from_home
from fx_rates import FxRate, manual_rate
from job_model import normalize_job
from job_status import (
    STATUS_ACTIVE,
    STATUS_CACHED,
    STATUS_GONE,
    STATUS_ONLINE_VERIFIED,
    STATUS_POSSIBLY_EXPIRED,
)
from salary_resolver import ORIGIN_NONE, resolve_salary

Job = dict[str, Any]
CategoryInfo = tuple[str, str]

# category_id: (dot_color, dashboard_label). IDs come from job_filter.py.
CATEGORY: dict[str, CategoryInfo] = {
    "tech":         ("#2B63B8", "Software / IT / AI"),
    "technical":    ("#5A6FD6", "Electronics & machining"),
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

COUNTRY_LABEL = {"IT": "Italy", "CH": "Switzerland"}
SENIORITY_LABEL = {
    "junior": "Junior", "mid": "Mid-level", "senior": "Senior", "manager": "Manager", "unknown": "Level not stated",
}
CONTRACT_LABEL = {
    "permanent": "Permanent", "fixed_term": "Fixed term", "apprenticeship": "Apprenticeship",
    "internship": "Internship", "freelance": "Freelance", "temp_agency": "Through an agency",
}
# status: (css class, text shown on the card, text used by the filter chip)
STATUS_INFO = {
    STATUS_ACTIVE: ("st-ok", "Seen in the latest scan", "Latest scan"),
    STATUS_ONLINE_VERIFIED: ("st-ok", "Page checked: still online", "Page checked"),
    STATUS_CACHED: ("st-warn", "Not re-checked: source unavailable", "Not re-checked"),
    STATUS_POSSIBLY_EXPIRED: ("st-old", "Possibly expired", "Possibly expired"),
    STATUS_GONE: ("st-gone", "No longer available", "Gone"),
}
UNKNOWN_STATUS = ("st-warn", "Status unknown", "Status unknown")
FILTER_ORDER_STATUS = (STATUS_ACTIVE, STATUS_ONLINE_VERIFIED, STATUS_CACHED, STATUS_POSSIBLY_EXPIRED, STATUS_GONE)
SALARY_FILTERS = (
    ("stated", "Written in the listing"),
    ("ai_estimate", "AI estimate"),
    ("unavailable", "Not available"),
)
PERIOD_LABEL = {"month": "month", "year": "year", "hour": "hour"}
BASIS_LABEL = {"gross": "gross", "net": "net", "unknown": "gross or net not stated"}
NO_DATE_TEXT = "Not stated"
NOT_TRACKED_TEXT = "Before tracking"


def _escape_html(value: object) -> str:
    """Escape a value before it is inserted into HTML."""
    return html_lib.escape(str(value))


def source_label(source_id: str) -> str:
    return SOURCE_LABEL.get(source_id, source_id)


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
    ai_description = str(job.get(AI_DESCRIPTION) or "").strip()
    if ai_description:
        return _escape_html(ai_description).replace("\n", "<br>")

    raw_description = str(job.get("description") or "").strip()
    if not raw_description:
        return ""
    cleaned = _clean_raw(raw_description)
    if not cleaned:
        return ""
    truncated = cleaned[:700]
    if len(cleaned) > 700:
        truncated += "..."
    return _escape_html(truncated)


def _description_block(job: Job) -> str:
    body = _description_html(job)
    if not body:
        return ""
    return f'<p class="card-desc">{body}</p>'


def _ai_block(job: Job) -> tuple[str, str]:
    """Return the data-ai value and the visible AI verdict block."""
    is_match = job.get(AI_SUITABLE)
    reason_html = _ai_reason_html(job)
    if is_match is True:
        return _ai_result("match", "ai-ok", "&#10003;", "Good match", reason_html)
    if is_match is False:
        return _ai_result("not_match", "ai-no", "&#10005;", "Not a match", reason_html)
    return "none", ""


def _ai_reason_html(job: Job) -> str:
    reason = _escape_html(job.get(AI_REASON, ""))
    if not reason:
        return ""
    return f'<p class="ai-why">{reason}</p>'


def _ai_result(filter_value: str, css_class: str, icon: str, label: str, reason_html: str) -> tuple[str, str]:
    return filter_value, _ai_html(css_class, icon, label, reason_html)


def _ai_html(css_class: str, icon: str, label: str, reason_html: str) -> str:
    return (
        f'<div class="ai {css_class}"><span class="ai-ico">{icon}</span><div>'
        f'<span class="ai-tag">{label}</span>{reason_html}</div></div>'
    )


# ---- salary

def _money(value: float) -> str:
    return f"{int(round(value)):,}"


def _amount_range(low: float, high: float) -> str:
    if low == high:
        return _money(low)
    return f"{_money(low)}&ndash;{_money(high)}"


def _written_amount(salary: dict) -> str:
    """The amount exactly as it is known: range, currency, period and gross/net."""
    period = PERIOD_LABEL.get(salary["period"], salary["period"])
    basis = BASIS_LABEL.get(salary["basis"], "")
    parts = [f'{_amount_range(salary["min"], salary["max"])} {_escape_html(salary["currency"])} / {period}']
    if basis:
        parts.append(basis)
    return ", ".join(parts)


def _net_text(net: dict) -> str:
    return f'~{_amount_range(net["monthly_min_eur"], net["monthly_max_eur"])} &euro;/month'


def _salary_block(job: Job, fx_rate: FxRate) -> str:
    """Salary panel: what is written or estimated, the net estimate and how it was made."""
    salary = resolve_salary(job, fx_rate)
    if salary["origin"] == ORIGIN_NONE:
        return _no_salary_panel(salary)
    rows = [
        f'<div class="salary" data-origin="{_escape_html(salary["origin"])}">',
        f'<div class="sal-head">Salary &middot; {_escape_html(salary["label"])}</div>',
        _salary_row("Amount", _written_amount(salary)),
        _breakdown_rows(salary),
        _net_row(salary),
        _assumptions_block(salary),
        "</div>",
    ]
    return "".join(rows)


def _no_salary_panel(salary: dict) -> str:
    note = "Not available"
    if salary["note"]:
        note = f'Not available. {_escape_html(salary["note"])}'
    return f'<div class="salary none" data-origin="{ORIGIN_NONE}"><div class="sal-head">Salary</div><p class="sal-note">{note}</p></div>'


def _breakdown_rows(salary: dict) -> str:
    """Show the deductions only for a single Swiss gross figure, where they are exact to the model."""
    net = salary["net"]
    if net is None or net.get("kind") != "cross_border":
        return ""
    if salary["min"] != salary["max"] or salary["period"] != "month":
        return ""
    details = net["details"]
    return "".join([
        _salary_row("Swiss social contributions", f'{details["social_chf"]:,} CHF', deduct=True),
        _salary_row("Ticino withholding tax", f'{details["withholding_chf"]:,} CHF', deduct=True),
        _salary_row("Additional Italian income tax", f'{details["extra_italian_tax_eur"]:,} &euro;', deduct=True),
    ])


def _net_row(salary: dict) -> str:
    net = salary["net"]
    if net is None:
        return '<p class="sal-note">No net estimate for this amount.</p>'
    label = "Net estimate"
    if net.get("kind") == "stated_net":
        label = "Net, as written"
    return f'<div class="sal-net"><span>{label}</span><span>{_net_text(net)}</span></div>'


def _assumptions_block(salary: dict) -> str:
    notes = list(salary["assumptions"])
    if salary["net"] is not None:
        notes.insert(0, "Indicative estimate, not a guaranteed take-home pay.")
    if not notes:
        return ""
    items = "".join(f"<li>{_escape_html(note)}</li>" for note in notes)
    return f'<details class="sal-why"><summary>How this is estimated</summary><ul>{items}</ul></details>'


def _salary_row(label: str, value: str, deduct: bool = False) -> str:
    row_class = "sal-row"
    prefix = ""
    if deduct:
        row_class = "sal-row deduct"
        prefix = "&minus;"
    return f'<div class="{row_class}"><span>{label}</span><span class="sal-num">{prefix}{value}</span></div>'


def _email_block(job: Job) -> str:
    email = str(job.get("email") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}", email):
        return ""
    escaped_email = _escape_html(email)
    return f'<a class="email-link" href="mailto:{escaped_email}">&#9993; {escaped_email}</a>'


# ---- location, dates, links

def _distance_of(job: Job) -> float | None:
    return km_from_home(str(job.get("city") or ""), str(job.get("country") or ""))


def _distance_label(km: float | None) -> str:
    if km is None:
        return "-"
    return f"{km:.0f} km"


def _safe_url(url: object) -> str:
    text = str(url or "")
    if text.startswith(("https://", "http://")):
        return _escape_html(text)
    return "#"


def _search_blob(job: Job) -> str:
    """Lowercase text used by the live search box."""
    fields = (str(job.get("title") or ""), str(job.get("company") or ""),
              str(job.get("city") or ""), str(job.get("place_name") or ""), str(job.get("email") or ""))
    return _escape_html(" ".join(fields).lower())


def _location_text(job: Job) -> str:
    """The place, with its country; an imprecise location is said to be imprecise."""
    raw_city = str(job.get("city") or "")
    place_name = str(job.get("place_name") or "")
    country = COUNTRY_LABEL.get(str(job.get("country") or ""), "")
    if job.get("location_certainty") != "exact":
        shown = raw_city or "Not stated"
        return f'{_escape_html(shown)} <span class="tag-soft">location not precise</span>'
    shown = place_name or raw_city
    if country:
        return f"{_escape_html(shown)}, {country}"
    return _escape_html(shown)


def _day(timestamp: object) -> str:
    return str(timestamp or "")[:10]


def _published_text(job: Job) -> str:
    published = str(job.get("published") or "")
    if published:
        return _escape_html(published)
    return NO_DATE_TEXT


def _checked_text(job: Job) -> str:
    checked = _day(job.get("last_verified") or job.get("last_seen"))
    if checked:
        return _escape_html(checked)
    return NOT_TRACKED_TEXT


def _status_info(job: Job) -> tuple[str, str, str]:
    return STATUS_INFO.get(str(job.get("status") or ""), UNKNOWN_STATUS)


def _status_badge(job: Job) -> str:
    css_class, label, _chip = _status_info(job)
    reason = _escape_html(job.get("status_reason") or "")
    title = ""
    if reason:
        title = f' title="{reason}"'
    return f'<span class="status {css_class}"{title}>{label}</span>'


def _source_text(job: Job) -> str:
    references = job.get("sources") or []
    labels = []
    for reference in references:
        label = source_label(str(reference.get("source") or ""))
        if label not in labels:
            labels.append(label)
    if not labels:
        labels = [source_label(str(job.get("source") or ""))]
    return _escape_html(" + ".join(labels))


def _other_links(job: Job) -> str:
    """Links to the same job on the other portals it was found on."""
    references = job.get("sources") or []
    main_url = str(job.get("url") or "")
    links = []
    for reference in references:
        url = str(reference.get("url") or "")
        if not url or url == main_url:
            continue
        label = _escape_html(source_label(str(reference.get("source") or "")))
        links.append(f'<a class="also-link" href="{_safe_url(url)}" target="_blank" rel="noopener noreferrer">{label} &#8599;</a>')
    if not links:
        return ""
    return '<div class="also"><span class="meta-k">Also on</span>' + "".join(links) + "</div>"


def _tags_row(job: Job) -> str:
    tags = [SENIORITY_LABEL.get(str(job.get("seniority") or "unknown"), "")]
    contract = CONTRACT_LABEL.get(str(job.get("contract_type") or ""), "")
    if contract:
        tags.append(contract)
    chips = "".join(f'<span class="tag">{_escape_html(tag)}</span>' for tag in tags if tag)
    return f'<div class="tags">{chips}</div>'


# ----------------------------------------------------------------
# Full card
# ----------------------------------------------------------------

def build_card(job: Job, fx_rate: FxRate | None = None) -> str:
    normalized_job = normalize_ai_fields(normalize_job(job))
    view = _card_view(normalized_job)
    return _card_html(normalized_job, view, fx_rate or manual_rate(None))


def _card_view(job: Job) -> dict[str, Any]:
    category_id = str(job.get("category") or "other")
    color, category_label = CATEGORY.get(category_id, CATEGORY["other"])
    km = _distance_of(job)
    km_attr = "9999"
    if km is not None:
        km_attr = f"{km:.1f}"
    ai_filter, ai_html = _ai_block(job)
    return {
        "category_id": category_id, "color": color, "category_label": category_label,
        "km": km, "km_attr": km_attr, "ai_filter": ai_filter, "ai_html": ai_html,
    }


def _card_html(job: Job, view: dict[str, Any], fx_rate: FxRate) -> str:
    salary = resolve_salary(job, fx_rate)
    main_column = [
        '<div class="card-main">', _card_header(view, job), _card_title(job), _tags_row(job),
        _description_block(job), view["ai_html"], "</div>",
    ]
    side_column = [
        '<div class="card-side">', _card_meta(job, view), _route_block(view),
        _salary_block(job, fx_rate), _email_block(job), _apply_link(job), _other_links(job), "</div>",
    ]
    return "\n".join([_card_open(job, view, salary), *main_column, *side_column, "</article>"])


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


def _card_open(job: Job, view: dict[str, Any], salary: dict) -> str:
    status = str(job.get("status") or "")
    sources = "|" + "|".join(str(ref.get("source") or "") for ref in job.get("sources") or []) + "|"
    net_value = ""
    if salary["sort_value"] is not None:
        net_value = f'{salary["sort_value"]:.0f}'
    attributes = {
        "data-category": view["category_id"], "data-ai": view["ai_filter"], "data-km": view["km_attr"],
        "data-country": job.get("country") or "", "data-seniority": job.get("seniority") or "unknown",
        "data-status": status, "data-salary": salary["origin"], "data-net": net_value,
        "data-sources": sources, "data-place": job.get("place_name") or "",
        "data-precise": "yes" if job.get("location_certainty") == "exact" else "no",
        "data-published": job.get("published") or "", "data-checked": _day(job.get("last_verified") or job.get("last_seen")),
        "data-search": _search_blob(job),
    }
    rendered = " ".join(f'{name}="{_escape_html(value)}"' for name, value in attributes.items())
    expired_class = ""
    if status in (STATUS_POSSIBLY_EXPIRED, STATUS_GONE):
        expired_class = " old"
    return f'<article class="card{expired_class}" {rendered} style="--accent:{view["color"]}">'


def _card_header(view: dict[str, Any], job: Job) -> str:
    return (
        '<div class="card-head">'
        f'<span class="card-cat">{view["category_label"]}</span>'
        f'{_status_badge(job)}</div>'
    )


def _card_title(job: Job) -> str:
    title = _escape_html(job.get("title", ""))
    company = _escape_html(job.get("company", "")) or "&nbsp;"
    return f'<h2 class="card-title">{title}</h2><p class="card-company">{company}</p>'


def _card_meta(job: Job, view: dict[str, Any]) -> str:
    return '<div class="card-meta">' + "".join(_card_meta_rows(job, view)) + "</div>"


def _card_meta_rows(job: Job, view: dict[str, Any]) -> list[str]:
    home_city_label = _escape_html(HOME_CITY)
    rows = [_meta_row("Location", _location_text(job))]
    if is_home_configured():
        rows.append(_meta_row(f"From {home_city_label}", _distance_label(view["km"])))
    rows.append(_meta_row("Source", _source_text(job)))
    rows.append(_meta_row("Published", _published_text(job)))
    rows.append(_meta_row("Last checked", _checked_text(job)))
    return rows


def _meta_row(label: str, value: str) -> str:
    return f'<div><span class="meta-k">{label}</span><span class="meta-v">{value}</span></div>'


def _apply_link(job: Job) -> str:
    return f'<a class="apply-btn" href="{_safe_url(job.get("url"))}" target="_blank" rel="noopener noreferrer">View listing <span class="arrow">&rarr;</span></a>'


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
<title>JobScraper - Lombardy and Ticino jobs</title>
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
#search, #sort, #place, #source {
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


/* Status, tags and filters added for freshness, location and salary transparency */
.status { font-size: 11.5px; font-weight: 700; padding: 2px 8px; border-radius: 2px;
          border: 1px solid currentColor; white-space: nowrap; }
.st-ok { color: var(--ok); }
.st-warn { color: #8A5A00; }
.st-old, .st-gone { color: var(--ink-3); }
.card.old { opacity: .72; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: -4px; }
.tag { font-size: 12px; color: var(--ink-2); background: var(--card-2); border: 1px solid var(--rule);
       border-radius: 2px; padding: 1px 8px; }
.tag-soft { font-family: var(--sans); font-size: 11px; font-weight: 600; color: #8A5A00; margin-left: 4px; }
.also { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; font-size: 12.5px; }
.also-link { color: var(--ink-2); }
.also-link:hover { color: var(--ink); }
.salary.none { background: transparent; border-style: dashed; }
.sal-why { font-size: 12px; color: var(--ink-3); }
.sal-why summary { cursor: pointer; }
.sal-why ul { padding-left: 18px; margin-top: 4px; display: grid; gap: 2px; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13.5px; color: var(--ink-2); cursor: pointer; }
select { width: 100%; background: var(--card); color: var(--ink); border: 1px solid var(--rule-2);
         border-radius: 3px; padding: 9px 11px; font: inherit; font-size: 14px; }

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
      <h1>JobScraper<span class="to">&rarr; __REGIONS__</span></h1>
      <span class="updated">Updated __NOW__</span>
    </div>
    <p class="subtitle">__SUBTITLE__</p>
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
        <option value="date">Newest published</option>
        <option value="checked">Most recently checked</option>
        __NEAREST_OPTION__
        <option value="net">Highest net salary</option>
      </select>
    </div>
    <p class="found" aria-live="polite"><b id="visible-n">__COUNT__</b> results</p>
    <div>
      <span class="field-label" id="field-label">Field</span>
      <div class="chips" role="group" aria-labelledby="field-label" data-filter="category">
        <button class="chip" data-value="all" aria-pressed="true">All <span class="n">__COUNT__</span></button>
        __CAT_CHIPS__
        __CHIP_AI__
      </div>
    </div>
    __FILTER_GROUPS__
    <div>
      <label class="field-label" for="place">Place</label>
      <select id="place"><option value="">All places</option>__PLACE_OPTIONS__</select>
    </div>
    <div>
      <label class="field-label" for="source">Source</label>
      <select id="source"><option value="">All sources</option>__SOURCE_OPTIONS__</select>
    </div>
    <label class="check"><input type="checkbox" id="precise"> Precise location only</label>
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
  Salary and distance figures are indicative estimates, not offers.__FX_NOTE__
</footer>

<script>
"use strict";

const state = {
  category: "all", country: "all", seniority: "all", status: "all", salary: "all",
  aiOnly: false, preciseOnly: false, query: "", place: "", source: ""
};
const grid = document.getElementById("grid");
const cards = Array.from(grid.querySelectorAll(".card"));

// Original order means newest first, as sorted by the generator.
cards.forEach((card, index) => { card.dataset.order = index; });

function matchesStatus(card) {
  if (state.status === "all") {
    return card.dataset.status !== "gone";
  }
  return card.dataset.status === state.status;
}

function matchesSalary(card) {
  if (state.salary === "all") {
    return true;
  }
  if (state.salary === "stated") {
    return card.dataset.salary === "stated" || card.dataset.salary === "extracted";
  }
  return card.dataset.salary === state.salary;
}

function cardMatches(card) {
  const data = card.dataset;
  const checks = [
    state.category === "all" || data.category === state.category,
    state.country === "all" || data.country === state.country,
    state.seniority === "all" || data.seniority === state.seniority,
    matchesStatus(card),
    matchesSalary(card),
    !state.aiOnly || data.ai === "match",
    !state.preciseOnly || data.precise === "yes",
    !state.query || data.search.includes(state.query),
    !state.place || data.place === state.place,
    !state.source || data.sources.includes("|" + state.source + "|")
  ];
  return checks.every(Boolean);
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

function numberOf(card, name, missing) {
  const value = parseFloat(card.dataset[name]);
  if (Number.isNaN(value)) {
    return missing;
  }
  return value;
}

function applySort(mode) {
  const sorted = [...cards];
  if (mode === "km") {
    sorted.sort((a, b) => numberOf(a, "km", 9999) - numberOf(b, "km", 9999));
  } else if (mode === "net") {
    sorted.sort((a, b) => numberOf(b, "net", -1) - numberOf(a, "net", -1));
  } else if (mode === "checked") {
    sorted.sort((a, b) => b.dataset.checked.localeCompare(a.dataset.checked) || a.dataset.order - b.dataset.order);
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

document.getElementById("place").addEventListener("change", (event) => {
  state.place = event.target.value;
  applyFilters();
});

document.getElementById("source").addEventListener("change", (event) => {
  state.source = event.target.value;
  applyFilters();
});

document.getElementById("precise").addEventListener("change", (event) => {
  state.preciseOnly = event.target.checked;
  applyFilters();
});

// Every chip group is a [data-filter] container; the AI chip is a separate toggle.
for (const group of document.querySelectorAll("[data-filter]")) {
  group.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) {
      return;
    }
    if (chip.id === "chip-ai") {
      state.aiOnly = !state.aiOnly;
      chip.setAttribute("aria-pressed", String(state.aiOnly));
    } else {
      state[group.dataset.filter] = chip.dataset.value;
      for (const button of group.querySelectorAll(".chip[data-value]")) {
        button.setAttribute("aria-pressed", String(button === chip));
      }
    }
    applyFilters();
  });
}

applyFilters();

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

def _count_by(jobs: list[Job], field_name: str, default: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        value = str(job.get(field_name) or default)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _chip(value: str, label: str, count: int, pressed: bool = False) -> str:
    return (
        f'<button class="chip" data-value="{_escape_html(value)}" aria-pressed="{str(pressed).lower()}">'
        f'{_escape_html(label)} <span class="n">{count}</span></button>'
    )


def _category_chips(counts: dict[str, int]) -> str:
    """Build one chip button for each category present in the current jobs."""
    chips: list[str] = []
    for category_id, (color, label) in CATEGORY.items():
        count = counts.get(category_id, 0)
        if count == 0:
            continue
        chips.append(
            f'<button class="chip" data-value="{category_id}" aria-pressed="false" style="--chip-accent:{color}">'
            f'<span class="chip-dot"></span>{label} <span class="n">{count}</span></button>'
        )
    return "\n      ".join(chips)


def _filter_group(title: str, group_id: str, chips: list[str]) -> str:
    if len(chips) < 2:
        return ""
    all_chip = '<button class="chip" data-value="all" aria-pressed="true">All</button>'
    return (
        f'<div><span class="field-label" id="label-{group_id}">{title}</span>'
        f'<div class="chips" role="group" aria-labelledby="label-{group_id}" data-filter="{group_id}">'
        f'{all_chip}{"".join(chips)}</div></div>'
    )


def _filter_groups(jobs: list[Job]) -> str:
    country_counts = _count_by(jobs, "country", "")
    seniority_counts = _count_by(jobs, "seniority", "unknown")
    status_counts = _count_by(jobs, "status", "")
    salary_counts = _salary_origin_counts(jobs)
    country_chips = [_chip(code, COUNTRY_LABEL[code], country_counts[code]) for code in COUNTRY_LABEL if code in country_counts]
    seniority_chips = [_chip(code, label, seniority_counts[code]) for code, label in SENIORITY_LABEL.items() if code in seniority_counts]
    status_chips = [_chip(code, STATUS_INFO[code][2], status_counts[code]) for code in FILTER_ORDER_STATUS if code in status_counts]
    salary_chips = [_chip(code, label, salary_counts[code]) for code, label in SALARY_FILTERS if code in salary_counts]
    return "".join([
        _filter_group("Country", "country", country_chips),
        _filter_group("Seniority", "seniority", seniority_chips),
        _filter_group("Freshness", "status", status_chips),
        _filter_group("Salary", "salary", salary_chips),
    ])


def _salary_origin_counts(jobs: list[Job]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        origin = resolve_salary(job)["origin"]
        if origin == "extracted":
            origin = "stated"
        counts[origin] = counts.get(origin, 0) + 1
    return counts


def _place_options(jobs: list[Job]) -> str:
    places = sorted({str(job.get("place_name")) for job in jobs if job.get("place_name")})
    return "".join(f'<option value="{_escape_html(place)}">{_escape_html(place)}</option>' for place in places)


def _source_options(jobs: list[Job]) -> str:
    sources = sorted(_all_sources(jobs))
    return "".join(f'<option value="{_escape_html(source)}">{_escape_html(source_label(source))}</option>' for source in sources)


def _all_sources(jobs: list[Job]) -> set[str]:
    sources: set[str] = set()
    for job in jobs:
        for reference in job.get("sources") or []:
            if reference.get("source"):
                sources.add(str(reference["source"]))
        if job.get("source"):
            sources.add(str(job["source"]))
    return sources


def _source_list(jobs: list[Job]) -> tuple[int, str]:
    """Return the number of sources and a readable source list actually present."""
    present_sources = _all_sources(jobs)
    if not present_sources:
        return 0, "-"
    names = sorted(source_label(source) for source in present_sources)
    return len(present_sources), " | ".join(names)


def _region_title(jobs: list[Job]) -> str:
    regions = {str(job.get("region") or "") for job in jobs}
    names = []
    if "LOM" in regions:
        names.append("Lombardy")
    if "TI" in regions:
        names.append("Ticino")
    if not names:
        return "Lombardy + Ticino"
    return " + ".join(names)


def _subtitle(jobs: list[Job], source_count: int) -> str:
    return f"Listings from {source_count} portals, {_region_title(jobs)}.{_distance_note()}"


def _fx_note(jobs: list[Job], fx_rate: FxRate) -> str:
    """Name the exchange rate only when a Swiss salary is on the page."""
    if not any(job.get("country") == "CH" for job in jobs):
        return ""
    source_text = _escape_html(fx_rate.source)
    if fx_rate.date:
        source_text += f" of {_escape_html(fx_rate.date)}"
    return f"<br>CHF converted at {fx_rate.eur_per_chf:.4f} EUR ({source_text})."


def generate_html(jobs: list[Job], output_path: str | Path = "index.html", fx_rate: FxRate | None = None) -> None:
    rate = fx_rate or manual_rate(None)
    normalized_jobs = [normalize_ai_fields(normalize_job(job)) for job in jobs]
    page = _dashboard_page(normalized_jobs, rate)
    Path(output_path).write_text(page, encoding="utf-8")
    print(f"[OK] Dashboard generated: {output_path} ({len(normalized_jobs)} jobs)")


def _dashboard_page(jobs: list[Job], fx_rate: FxRate) -> str:
    page = _fill_template(_template_replacements(jobs, fx_rate))
    if not jobs:
        return _show_empty_state(page)
    return page


def _template_replacements(jobs: list[Job], fx_rate: FxRate) -> dict[str, str]:
    matches = sum(1 for job in jobs if job.get(AI_SUITABLE) is True)
    has_ai_results = any(job.get(AI_SUITABLE) is not None for job in jobs)
    counts = _count_by(jobs, "category", "other")
    source_count, source_names = _source_list(jobs)
    ordered_jobs = _newest_first(jobs)
    return {
        "__NOW__": _escape_html(datetime.now().strftime("%Y-%m-%d - %H:%M")),
        "__REGIONS__": _escape_html(_region_title(jobs)),
        "__SUBTITLE__": _escape_html(_subtitle(jobs, source_count)),
        "__MATCH_TALLY__": _match_tally(matches, has_ai_results),
        "__CHIP_AI__": _ai_chip(matches, has_ai_results), "__COUNT__": str(len(jobs)),
        "__NSOURCES__": str(source_count), "__SOURCELIST__": _escape_html(source_names),
        "__CAT_CHIPS__": _category_chips(counts), "__FILTER_GROUPS__": _filter_groups(jobs),
        "__PLACE_OPTIONS__": _place_options(jobs), "__SOURCE_OPTIONS__": _source_options(jobs),
        "__NEAREST_OPTION__": _nearest_option(),
        "__CARDS__": "\n".join(_card_html(job, _card_view(job), fx_rate) for job in ordered_jobs),
        "__EMPTY_SUB__": _empty_subtitle(jobs),
        "__FX_NOTE__": _fx_note(jobs, fx_rate),
    }


def _newest_first(jobs: list[Job]) -> list[Job]:
    """Published date first; jobs without a date follow, most recently first seen first."""
    by_first_seen = sorted(jobs, key=lambda job: str(job.get("first_seen") or ""), reverse=True)
    return sorted(by_first_seen, key=lambda job: str(job.get("published") or ""), reverse=True)


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
