"""
Scraper per Manpower Svizzera (www.manpower.ch) — offerte in Ticino.

Manpower non supporta filtro per URL né POST: si usano le city pages.
URL Ticino: /it/trova-lavoro/citta/lugano  e  /it/trova-lavoro/citta/bellinzone
Paginazione: /it/trova-lavoro/citta/{slug}/p{N}  (N = 1, 2, 3 …)
"""

import re
from datetime import date

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job

BASE_URL  = "https://www.manpower.ch"
MAX_PAGES = 10

# Città ticinesi con filiale Manpower che hanno annunci dedicati
_TICINO_CITIES = [
    ("lugano",     "Lugano"),
    ("bellinzone", "Bellinzona"),
]


def _page_closed(exc: Exception) -> bool:
    """True se l'eccezione indica che la pagina/contesto è stato chiuso."""
    msg = str(exc).lower()
    return "closed" in msg or "targetclosed" in type(exc).__name__.lower()


def _parse_date(text: str) -> str:
    """'09/06/2026' → '2026-06-09'"""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date.today().isoformat()


_JS_EXTRACT = r"""() => {
    const results = [];
    const seen = new Set();
    const anchors = document.querySelectorAll('a[href*="/it/job/"]');
    for (const a of anchors) {
        const href = a.getAttribute('href') || '';
        if (!href || seen.has(href)) continue;
        seen.add(href);

        const title = a.innerText.trim();
        // Salta elementi con innerText che sono aria-label (es. "link to /it/job/...")
        if (!title || title.startsWith('link to')) continue;

        // Il contenitore card è il div.card-body o il closest element con classe "card"
        const card = a.closest('[class*="card"]') || a.closest('li') || a.parentElement;
        if (!card) continue;

        const lines = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        // Struttura attesa: [data, ("NEW"), "Manpower", titolo, città, tipo, settore]
        let city = '', jobType = '', dateStr = '';

        for (let i = 0; i < lines.length; i++) {
            if (lines[i] === title) {
                city    = lines[i + 1] || '';
                jobType = lines[i + 2] || '';
                break;
            }
        }
        // Data in formato DD/MM/YYYY
        const dateMatch = lines[0] && lines[0].match(/^\d{2}\/\d{2}\/\d{4}$/);
        if (dateMatch) dateStr = lines[0];

        const url = href.startsWith('http') ? href : 'https://www.manpower.ch' + href;
        results.push({ href, title, city, jobType, dateStr, url });
    }
    return results;
}"""


def _scrape_city(page, city_slug: str, city_name: str, seen_urls: set) -> list:
    jobs = []
    for page_num in range(MAX_PAGES):
        if page_num == 0:
            url = f"{BASE_URL}/it/trova-lavoro/citta/{city_slug}"
        else:
            url = f"{BASE_URL}/it/trova-lavoro/citta/{city_slug}/p{page_num}"

        print(f"  [manpower.ch] {city_name} pagina {page_num + 1}…")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            if _page_closed(e):
                print(f"  [manpower.ch] {city_name}: pagina chiusa durante navigazione — stop")
                break
            page.wait_for_timeout(3000)

        if page_num == 0:
            dismiss_cookie_dialog(page)
            page.wait_for_timeout(1500)

        # Aspetta che appaiano i link ai job
        try:
            page.wait_for_selector('a[href*="/it/job/"]', timeout=8000)
        except Exception as e:
            if _page_closed(e):
                print(f"  [manpower.ch] {city_name}: pagina chiusa durante attesa — stop")
                break
            print(f"  [manpower.ch] {city_name}: nessun link job trovato — stop")
            if page_num == 0:
                shot = debug_artifacts(page, "manpower_ch_nocards")
                run_report.set_status(
                    "manpower.ch", "selector_broken",
                    f"{city_name}: nessun link job a pagina 1",
                    final_url=url, screenshot=shot)
            break

        try:
            human_scroll(page)
            page.wait_for_timeout(1000)
        except Exception as e:
            if _page_closed(e):
                print(f"  [manpower.ch] {city_name}: pagina chiusa durante scroll — stop")
                break
            raise

        try:
            raw = page.evaluate(_JS_EXTRACT)
        except Exception as e:
            if _page_closed(e):
                print(f"  [manpower.ch] {city_name}: pagina chiusa durante estrazione — stop")
                break
            raise
        if not raw:
            break

        batch = []
        for item in raw:
            job_url = item.get("url", "")
            title   = item.get("title", "").strip()
            if not title or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            raw_date = item.get("dateStr", "")
            batch.append({
                "title":    title,
                "company":  "Manpower",
                "city":     item.get("city", city_name).strip(),
                "date":     _parse_date(raw_date) if raw_date else date.today().isoformat(),
                "url":      job_url,
                "category": categorize_job(title),
                "source":   "manpower.ch",
            })

        if not batch:
            break

        jobs.extend(batch)
        print(f"  [manpower.ch] {city_name}: {len(batch)} nuovi (tot. {len(jobs)})")
        human_delay(1.5, 3.5)

    return jobs


@retry()
def scrape_manpower_ch(context) -> list:
    all_jobs  = []
    seen_urls = set()

    for city_slug, city_name in _TICINO_CITIES:
        page = new_stealth_page(context)
        try:
            city_jobs = _scrape_city(page, city_slug, city_name, seen_urls)
        finally:
            try:
                page.close()
            except Exception:
                pass
        all_jobs.extend(city_jobs)

    print(f"  [manpower.ch] {len(all_jobs)} annunci trovati")
    return all_jobs
