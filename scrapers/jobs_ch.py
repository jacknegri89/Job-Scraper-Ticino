from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import SEARCH_TERMS, categorize_job
import urllib.parse

BASE_URL   = "https://www.jobs.ch"
SEARCH_URL = "https://www.jobs.ch/en/vacancies/?term={term}&location=ticino&page={page}"
MAX_PAGES  = 20   # limite di sicurezza; si ferma prima quando la pagina è vuota


def _extract_jobs_from_page(page) -> list:
    jobs = []
    cards = page.query_selector_all('a[data-cy="job-link"]')
    for card in cards:
        try:
            title = card.get_attribute("title") or ""
            href  = card.get_attribute("href") or ""
            url   = f"{BASE_URL}{href}" if href.startswith("/") else href

            paras = card.query_selector_all("p")
            date_text = paras[0].text_content().strip() if len(paras) > 0 else ""
            city_text = paras[1].text_content().strip() if len(paras) > 1 else ""

            company_el = card.query_selector("p[class*='fw_bol']")
            company    = company_el.text_content().strip() if company_el else ""

            if title and url:
                jobs.append({
                    "title":    title,
                    "company":  company,
                    "city":     city_text,
                    "date":     date_text,
                    "url":      url,
                    "category": categorize_job(title),
                    "source":   "jobs.ch",
                })
        except Exception as e:
            print(f"[WARN] Errore card jobs.ch: {e}")
    return jobs


@retry()
def scrape_jobs_ch(context, search_terms: list = None) -> list:
    if search_terms is None:
        search_terms = SEARCH_TERMS

    all_jobs  = []
    seen_urls = set()   # URL già raccolti (globale tra tutti i termini)
    page = new_stealth_page(context)
    try:
        for term in search_terms:
            print(f"[jobs.ch] Cerco: '{term}'")
            for page_num in range(1, MAX_PAGES + 1):
                url = SEARCH_URL.format(term=urllib.parse.quote_plus(term), page=page_num)
                try:
                    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    dismiss_cookie_dialog(page)
                    human_scroll(page)
                    human_delay(3.0, 7.0)

                    jobs = _extract_jobs_from_page(page)
                    if not jobs:
                        break   # pagina genuinamente vuota

                    new_jobs = [j for j in jobs if j["url"] not in seen_urls]
                    if not new_jobs:
                        break
                    for j in new_jobs:
                        seen_urls.add(j["url"])
                    all_jobs.extend(new_jobs)
                    print(f"  pag.{page_num}: {len(new_jobs)} nuovi ({len(jobs)} totali)")

                except Exception as e:
                    print(f"[WARN] {url}: {e}")
                    break

        print(f"[jobs.ch] Totale grezzo: {len(all_jobs)}")
        return all_jobs
    finally:
        page.close()
