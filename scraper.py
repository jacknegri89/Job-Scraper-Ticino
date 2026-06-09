from datetime import datetime
from playwright.sync_api import sync_playwright

from scrapers import create_browser_context, save_session
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.carriera_ch import scrape_carriera_ch
from filters import filter_jobs
from html_generator import generate_html

# ─── Hook LLM opzionale (commentato) ─────────────────────────────────────────
# Per attivarlo in futuro: pip install anthropic
# Imposta la variabile d'ambiente: ANTHROPIC_API_KEY=sk-ant-...
#
# def analyze_with_llm(job_text: str) -> dict:
#     import anthropic, json
#     client = anthropic.Anthropic()
#     msg = client.messages.create(
#         model="claude-sonnet-4-6",
#         max_tokens=256,
#         messages=[{"role": "user", "content": (
#             "Analizza questo annuncio di lavoro svizzero. Rispondi SOLO in JSON:\n"
#             '{"stipendio": "...", "esclusi_frontalieri": true/false}\n\n' + job_text
#         )}],
#     )
#     return json.loads(msg.content[0].text)
# ─────────────────────────────────────────────────────────────────────────────


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
        except Exception as e:
            print(f"[ERRORE CRITICO] {e}")
        finally:
            save_session(context)
            browser.close()

    valid = filter_jobs(raw_jobs)
    print(f"\n[FILTER] {len(raw_jobs)} grezzi → {len(valid)} validi")

    generate_html(valid)

    elapsed = int((datetime.now() - start).total_seconds())
    print(f"[DONE] Completato in {elapsed}s. Apri index.html nel browser.")


if __name__ == "__main__":
    main()
