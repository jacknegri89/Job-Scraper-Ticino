from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import KEYWORDS, categorize_job
import urllib.parse

BASE_URL   = "https://www.jobs.ch"
SEARCH_URL = "https://www.jobs.ch/en/vacancies/?term={term}&location=ticino&page={page}"
MAX_PAGES  = 3


def _extract_jobs_from_page(page, category: str) -> list:
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


@retry(max_attempts=3)
def scrape_jobs_ch(context, keywords_dict: dict = None) -> list:
    if keywords_dict is None:
        keywords_dict = KEYWORDS

    all_jobs = []
    page = new_stealth_page(context)

    for category, keywords in keywords_dict.items():
        for keyword in keywords:
            print(f"[jobs.ch] '{keyword}' ({category})")
            for page_num in range(1, MAX_PAGES + 1):
                url = SEARCH_URL.format(term=urllib.parse.quote_plus(keyword), page=page_num)
                try:
                    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    dismiss_cookie_dialog(page)
                    human_scroll(page)
                    human_delay(3.0, 7.0)

                    jobs = _extract_jobs_from_page(page, category)
                    if not jobs:
                        break
                    all_jobs.extend(jobs)
                    print(f"  pag.{page_num}: {len(jobs)} annunci")
                    if len(jobs) < 20:
                        break
                except Exception as e:
                    print(f"[WARN] {url}: {e}")
                    break

    page.close()
    print(f"[jobs.ch] Totale grezzo: {len(all_jobs)}")
    return all_jobs
