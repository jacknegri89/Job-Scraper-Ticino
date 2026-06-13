from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import categorize_job

LIST_URL  = "https://www.carriera.ch/offerte/annunci-offerte-lavoro_0_0_{page}.html"
MAX_PAGES = 50  # limite di sicurezza; si ferma prima quando una pagina non porta nuovi annunci


def _extract_jobs_from_page(page) -> list:
    jobs = []
    rows = page.query_selector_all("tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) != 6:
            continue
        try:
            date_text   = cells[0].text_content().strip()
            company_img = cells[1].query_selector("img")
            company     = (company_img.get_attribute("alt") or "").strip() if company_img else cells[1].text_content().strip()
            title_link  = cells[2].query_selector("a")
            if not title_link:
                continue
            title = title_link.text_content().strip()
            url   = title_link.get_attribute("href") or ""
            city  = cells[3].text_content().strip()

            if not title or not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.carriera.ch{url}"

            jobs.append({
                "title":    title,
                "company":  company,
                "city":     city,
                "date":     date_text,
                "url":      url,
                "category": categorize_job(title),
                "source":   "carriera.ch",
            })
        except Exception as e:
            print(f"[WARN] Errore riga carriera.ch: {e}")
    return jobs


@retry()
def scrape_carriera_ch(context) -> list:
    all_jobs  = []
    seen_urls = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(MAX_PAGES):
            url = LIST_URL.format(page=page_num)
            print(f"[carriera.ch] Pagina {page_num + 1}")
            try:
                page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                dismiss_cookie_dialog(page)
                human_scroll(page)
                human_delay(3.0, 7.0)

                jobs = _extract_jobs_from_page(page)
                if not jobs:
                    break
                new_jobs = [j for j in jobs if j["url"] not in seen_urls]
                if not new_jobs:
                    break   # pagina ripetuta → fine paginazione reale
                for j in new_jobs:
                    seen_urls.add(j["url"])
                all_jobs.extend(new_jobs)
                print(f"  {len(new_jobs)} nuovi ({len(jobs)} totali)")
            except Exception as e:
                print(f"[WARN] {url}: {e}")
                break

        print(f"[carriera.ch] Totale grezzo: {len(all_jobs)}")
        return all_jobs
    finally:
        page.close()
