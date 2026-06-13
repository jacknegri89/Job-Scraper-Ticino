"""
Scraper per Orienta Svizzera (www.orienta.ch)

URL lista: /it/orienta-job/offerte-di-lavoro.html?page=N
49 annunci su ~5 pagine, tutti in Ticino (filiale Lugano/Manno).
Struttura: article > a[href*='/offerta-di-lavoro/'] > h2
           righe "Data" / "Sede" come coppie di righe nel testo.
           Formato Sede live: "Svizzera, Ticino, Città" → si prende l'ultima parte.
"""

from datetime import datetime
from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import categorize_job

BASE_URL  = "https://www.orienta.ch"
LIST_URL  = "https://www.orienta.ch/it/orienta-job/offerte-di-lavoro.html"
MAX_PAGES = 10


def _parse_date(raw: str) -> str:
    """'09/06/2026 Nuovo' → '2026-06-09'"""
    try:
        return datetime.strptime(raw.split()[0], "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return raw


def _extract_jobs(page) -> list:
    jobs = []
    for article in page.query_selector_all("article"):
        link_el = article.query_selector("a[href*='/offerta-di-lavoro/']")
        if not link_el:
            continue
        href = link_el.get_attribute("href") or ""
        url = (BASE_URL + href) if href.startswith("/") else href
        h2 = link_el.query_selector("h2")
        title = (h2.inner_text() if h2 else link_el.inner_text()).strip()
        if not title:
            continue

        # Le etichette "Data" e "Sede" appaiono come righe separate, seguite dal valore
        lines = [l.strip() for l in article.inner_text().splitlines() if l.strip()]
        city = date = ""
        for i, line in enumerate(lines):
            if line == "Sede" and i + 1 < len(lines):
                parts = lines[i + 1].split(",")
                # Formato live: "Svizzera, Ticino, Chiasso" → la città è l'ultima parte
                city = parts[-1].strip()
            elif line == "Data" and i + 1 < len(lines):
                date = _parse_date(lines[i + 1])

        jobs.append({
            "title":    title,
            "company":  "Orienta SA",
            "city":     city,
            "date":     date,
            "url":      url,
            "category": categorize_job(title),
            "source":   "orienta.ch",
        })
    return jobs


@retry()
def scrape_orienta_ch(context) -> list:
    all_jobs  = []
    seen_urls = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            url = f"{LIST_URL}?page={page_num}"
            print(f"  [orienta.ch] Pagina {page_num}…")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            if page_num == 1:
                dismiss_cookie_dialog(page)
                page.wait_for_timeout(1500)

            human_scroll(page)
            page.wait_for_timeout(1000)

            jobs = _extract_jobs(page)
            if not jobs:
                break
            new_jobs = [j for j in jobs if j["url"] not in seen_urls]
            if not new_jobs:
                break   # pagina ripetuta → fine paginazione reale
            for j in new_jobs:
                seen_urls.add(j["url"])
            all_jobs.extend(new_jobs)
            print(f"  [orienta.ch] {len(new_jobs)} nuovi (tot. {len(all_jobs)})")
            human_delay(2.0, 4.0)

        return all_jobs
    finally:
        page.close()
