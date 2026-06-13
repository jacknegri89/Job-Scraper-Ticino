"""
Scraper per Gi Group Switzerland (ch.gigroup.com/it/posizioni-aperte/)

Struttura verificata live:
- Card:   .ggp-job-item
- Titolo: h2.ggp-job-item-title
- Città:  .job-item-meta-row con .bi-geo-alt → "Città, Provincia, Cantone"
- Data:   .job-item-meta-row con .bi-calendar2-minus → "DD/MM/YYYY"
- URL:    a.ggp-job-item-detail-btn → relativo, base https://ch.gigroup.com
- Paginazione: ?npage=N
"""

from datetime import datetime

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import categorize_job

BASE_URL = "https://ch.gigroup.com"
LIST_URL = "https://ch.gigroup.com/it/posizioni-aperte/?npage={page}"
MAX_PAGES = 20  # limite di sicurezza; si ferma prima quando la pagina è vuota


def _parse_date(raw: str) -> str:
    """Converte 'DD/MM/YYYY' → 'YYYY-MM-DD'. Ritorna stringa originale se fallisce."""
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return raw.strip()


def _extract_jobs_from_page(page) -> list:
    cards = page.query_selector_all(".ggp-job-item")
    jobs = []
    for card in cards:
        try:
            # Titolo
            title_el = card.query_selector("h2.ggp-job-item-title")
            title = title_el.inner_text().strip() if title_el else ""
            if not title:
                continue

            # URL
            url_el = card.query_selector("a.ggp-job-item-detail-btn")
            href = url_el.get_attribute("href") if url_el else ""
            if href and href.startswith("/"):
                href = BASE_URL + href
            if not href:
                continue

            # Metadati dalle righe con icona Bootstrap
            city = ""
            date = ""
            meta_rows = card.query_selector_all(".job-item-meta-row")
            for row in meta_rows:
                icon = row.query_selector("span.bi")
                if not icon:
                    continue
                icon_class = icon.get_attribute("class") or ""
                text_el = row.query_selector("div:last-child span")
                text = text_el.inner_text().strip() if text_el else ""

                if "bi-geo-alt" in icon_class:
                    # "Chiasso, Mendrisio, Tessin" → prendi solo la prima parte
                    city = text.split(",")[0].strip()
                elif "bi-calendar2-minus" in icon_class:
                    date = _parse_date(text)

            jobs.append({
                "title":    title,
                "company":  "Gi Group SA",
                "city":     city,
                "date":     date,
                "url":      href,
                "category": categorize_job(title),
                "source":   "gigroup.ch",
            })
        except Exception as e:
            print(f"[WARN] Errore card gigroup.ch: {e}")
            continue
    return jobs


@retry()
def scrape_gigroup_ch(context) -> list:
    all_jobs  = []
    seen_urls = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            url = LIST_URL.format(page=page_num)
            print(f"  [gigroup.ch] Pagina {page_num}")

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            dismiss_cookie_dialog(page)
            page.wait_for_timeout(2000)
            human_scroll(page)

            jobs = _extract_jobs_from_page(page)
            if not jobs:
                break
            new_jobs = [j for j in jobs if j["url"] not in seen_urls]
            if not new_jobs:
                break   # pagina ripetuta → fine paginazione reale
            for j in new_jobs:
                seen_urls.add(j["url"])
            all_jobs.extend(new_jobs)
            print(f"  [gigroup.ch] {len(new_jobs)} nuovi (tot. {len(all_jobs)})")
            human_delay(2.0, 5.0)

        return all_jobs
    finally:
        page.close()
