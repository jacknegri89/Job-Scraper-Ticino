from datetime import datetime
from playwright.sync_api import sync_playwright

from scrapers import create_browser_context, save_session, fetch_description
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.carriera_ch import scrape_carriera_ch
from scrapers.gigroup_ch import scrape_gigroup_ch
from filters import filter_jobs
from html_generator import generate_html
from llm_analyzer import analyze_jobs


def main():
    start = datetime.now()
    print(f"[START] {start.strftime('%d/%m/%Y %H:%M')}")

    raw_jobs = []

    with sync_playwright() as p:
        browser, context = create_browser_context(p)
        try:
            print("\n=== JOBS.CH ===")
            raw_jobs.extend(scrape_jobs_ch(context))

            print("\n=== CARRIERA.CH ===")
            raw_jobs.extend(scrape_carriera_ch(context))

            print("\n=== GI GROUP CH ===")
            raw_jobs.extend(scrape_gigroup_ch(context))

            valid = filter_jobs(raw_jobs)
            print(f"\n[FILTER] {len(raw_jobs)} grezzi → {len(valid)} validi")

            # Recupera descrizione completa per ogni annuncio valido
            if valid:
                print(f"\n=== DESCRIZIONI ({len(valid)} annunci) ===")
                for i, job in enumerate(valid, start=1):
                    desc = fetch_description(context, job.get("url", ""))
                    job["description"] = desc
                    print(f"[DESC] {i}/{len(valid)} — {job.get('title', '')[:50]}")

        except Exception as e:
            print(f"[ERRORE CRITICO] {e}")
            valid = filter_jobs(raw_jobs)
        finally:
            save_session(context)
            browser.close()

    print(f"\n[FILTER] {len(raw_jobs)} grezzi → {len(valid)} validi")

    valid = analyze_jobs(valid)

    generate_html(valid)

    elapsed = int((datetime.now() - start).total_seconds())
    print(f"[DONE] Completato in {elapsed}s. Apri index.html nel browser.")


if __name__ == "__main__":
    main()
