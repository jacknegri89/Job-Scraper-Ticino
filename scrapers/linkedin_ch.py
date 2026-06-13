"""
Scraper per LinkedIn Jobs (www.linkedin.com/jobs) — annunci in Ticino, CH.

URL lista pubblica (senza login):
  https://www.linkedin.com/jobs/search/?keywords=&location=Ticino%2C+Switzerland&start=N

LinkedIn mostra annunci pubblicamente senza login; appare un modale di sign-in
ma non blocca il DOM. Si usa anche l'endpoint guest API per evitare il modale:
  https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?...&start=N

Struttura DOM confermata (2026-06) — pagina pubblica:
  li.base-card                   → wrapper card
  a.base-card__full-link         → anchor con href al job
  h3.base-search-card__title     → titolo job
  h4.base-search-card__subtitle a → azienda
  span.job-search-card__location → città
  time[datetime]                 → data ISO YYYY-MM-DD (attributo datetime)
  (fallback: innerText relativo "3 weeks ago" etc.)

Paginazione: &start=0, &start=25, &start=50 … (25 risultati per pagina).
MAX_PAGES = 5  →  125 annunci massimi per run.

Se rileva authwall/login redirect → restituisce [] senza eccezione.
"""

import re
from datetime import date, timedelta

from scrapers import new_stealth_page, human_delay, human_scroll, retry
from scrapers.session import has_auth_state, auth_state_path
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job


# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
BASE_URL  = "https://www.linkedin.com"
LIST_URL  = "https://www.linkedin.com/jobs/search/"
MAX_PAGES = 5   # 25 risultati × 5 = 125 max

# Filtriamo per Ticino, Svizzera — incluse varianti di ricerca per massimizzare
# la copertura del distretto di Mendrisio (Chiasso, Mendrisio, Stabio…)
_SEARCH_LOCATION = "Ticino%2C+Switzerland"

_BLOCKED_SIGNALS = (
    "authwall", "/login", "checkpoint/lg", "sign-in",
    "access denied", "403 forbidden",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blocked(page) -> bool:
    """True se LinkedIn mostra un authwall o redirect al login."""
    try:
        url   = page.url.lower()
        title = page.title().lower()
        return any(s in url or s in title for s in _BLOCKED_SIGNALS)
    except Exception:
        return False


def _relative_to_date(text: str) -> str:
    """
    Converte date relative/ISO in YYYY-MM-DD.
    Gestisce sia l'attributo datetime (già ISO) sia testo come
    '3 weeks ago', '2 days ago', '1 month ago', 'just now'.
    """
    today = date.today()
    t = text.strip()

    # Attributo datetime già in formato ISO YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}', t):
        return t[:10]

    t_lower = t.lower()
    if not t_lower or "just" in t_lower or "now" in t_lower or "oggi" in t_lower:
        return today.isoformat()

    # "X hours ago" / "X ore fa"
    if re.search(r'\d+\s*(hour|ora|ore)', t_lower):
        return today.isoformat()

    # "X days ago" / "X giorni fa"
    m = re.search(r'(\d+)\s*day', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\s*giorn', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()

    # "X weeks ago" / "X settimane fa"
    m = re.search(r'(\d+)\s*week', t_lower)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\s*settiman', t_lower)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()

    # "X months ago" / "X mesi fa"
    m = re.search(r'(\d+)\s*month', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()
    m = re.search(r'(\d+)\s*mes', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()

    return today.isoformat()


def _clean_url(href: str) -> str:
    """Rimuove parametri di tracking dall'URL LinkedIn, tenendo solo il path."""
    if not href:
        return ""
    # Tronca al "?" per rimuovere position=, pageNum=, refId=, trackingId=
    return href.split("?")[0]


# ---------------------------------------------------------------------------
# JavaScript estrattore DOM (eseguito nel browser)
# ---------------------------------------------------------------------------

_JS_EXTRACT = r"""() => {
    const results = [];
    const seen = new Set();

    // LinkedIn usa sia <li class="base-card ..."> sia <div class="base-card ...">
    // come wrapper per ogni annuncio nella lista pubblica.
    // Selezioniamo tutti gli elementi che hanno la classe base-card.
    const cards = document.querySelectorAll('[class*="base-card"]');

    for (const card of cards) {
        // URL: anchor principale del card
        const anchor = (
            card.querySelector('a.base-card__full-link') ||
            card.querySelector('a[href*="/jobs/view/"]') ||
            card.querySelector('a[href*="linkedin.com/jobs"]')
        );
        if (!anchor) continue;

        const href = anchor.getAttribute('href') || '';
        // Usa href pulito (senza tracking) come chiave dedup
        const cleanHref = href.split('?')[0];
        if (!cleanHref || seen.has(cleanHref)) continue;
        seen.add(cleanHref);

        // Titolo
        const titleEl = (
            card.querySelector('h3.base-search-card__title') ||
            card.querySelector('[class*="base-search-card__title"]') ||
            card.querySelector('h3') ||
            anchor
        );
        const title = (titleEl ? titleEl.innerText : '').trim();
        if (!title) continue;

        // Azienda
        const companyEl = (
            card.querySelector('h4.base-search-card__subtitle a') ||
            card.querySelector('h4.base-search-card__subtitle') ||
            card.querySelector('[class*="base-search-card__subtitle"]') ||
            card.querySelector('h4')
        );
        // Alcuni nomi azienda includono " | domain.ch" — rimuoviamo il suffisso
        const company = (companyEl ? companyEl.innerText : '').trim().replace(/\s*\|.*$/, '');

        // Città
        const cityEl = (
            card.querySelector('span.job-search-card__location') ||
            card.querySelector('[class*="job-search-card__location"]')
        );
        const city = (cityEl ? cityEl.innerText : '').trim();

        // Data: attributo datetime (ISO) o testo relativo
        const timeEl = card.querySelector('time[datetime]');
        const dateRaw = timeEl
            ? (timeEl.getAttribute('datetime') || timeEl.innerText || '')
            : (card.querySelector('[class*="date"], [class*="listdate"]') || {innerText: ''}).innerText || '';

        results.push({
            href: cleanHref,
            title,
            company,
            city,
            dateRaw: dateRaw.trim(),
        });
    }
    return results;
}"""


# ---------------------------------------------------------------------------
# Scraper principale
# ---------------------------------------------------------------------------

@retry()
def scrape_linkedin_ch(context) -> list:
    """
    Se esiste una sessione salvata manualmente (python scraper.py --auth linkedin)
    la usa in un contesto dedicato; altrimenti modalità pubblica senza login.
    Mai tentativi di login automatico.
    """
    all_jobs  = []
    seen_urls = set()

    auth_ctx = None
    if has_auth_state("linkedin"):
        try:
            auth_ctx = context.browser.new_context(
                storage_state=str(auth_state_path("linkedin")),
                locale="it-CH", timezone_id="Europe/Zurich",
            )
            print("  [linkedin.ch] Uso la sessione autenticata salvata")
        except Exception as e:
            print(f"  [linkedin.ch] Sessione salvata illeggibile ({e}) — modalità pubblica")
            auth_ctx = None

    page = new_stealth_page(auth_ctx or context)
    try:
        for page_num in range(MAX_PAGES):
            start = page_num * 25
            url = (
                f"{LIST_URL}?keywords=&location={_SEARCH_LOCATION}"
                f"&f_TPR=r2592000"   # ultimi 30 giorni
                f"&start={start}"
            )
            print(f"  [linkedin.ch] Pagina {page_num + 1} (start={start})…")

            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"  [linkedin.ch] Errore navigazione: {e}")
                    break

            # Controlla authwall / redirect login — non si aggira, si segnala
            if _is_blocked(page):
                shot = debug_artifacts(page, "linkedin_ch_authwall")
                if auth_ctx:
                    reason = ("authwall nonostante la sessione salvata — probabilmente "
                              "scaduta: riesegui python scraper.py --auth linkedin")
                else:
                    reason = "authwall — per l'accesso completo: python scraper.py --auth linkedin"
                run_report.set_status("linkedin.ch", "requires_manual_login", reason,
                                      final_url=page.url, screenshot=shot)
                break

            # Chiudi eventuali modali di sign-in (non bloccanti, solo cleanup)
            try:
                dismiss_btn = page.query_selector(
                    'button[aria-label*="Dismiss"], '
                    'button[aria-label*="Close"], '
                    'button.modal__dismiss'
                )
                if dismiss_btn and dismiss_btn.is_visible():
                    dismiss_btn.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Attendi che i card siano presenti nel DOM
            card_loaded = False
            for wait_sel in [
                '[class*="base-card"]',
                'a[href*="/jobs/view/"]',
                'ul.jobs-search__results-list',
            ]:
                try:
                    page.wait_for_selector(wait_sel, timeout=8000)
                    card_loaded = True
                    break
                except Exception:
                    pass

            if not card_loaded:
                print(f"  [linkedin.ch] Nessun card trovato (title={page.title()[:60]!r}) — stop")
                if page_num == 0:
                    shot = debug_artifacts(page, "linkedin_ch_nocards")
                    hint = (" — NB: con sessione autenticata il DOM è diverso da"
                            " quello pubblico; selettori da adattare") if auth_ctx else ""
                    run_report.set_status(
                        "linkedin.ch", "selector_broken",
                        f"nessun card a pagina 1 (title={page.title()[:50]!r}){hint}",
                        final_url=page.url, screenshot=shot)
                break

            human_scroll(page)
            page.wait_for_timeout(1500)

            raw = page.evaluate(_JS_EXTRACT)
            if not raw:
                print(f"  [linkedin.ch] Pagina vuota — stop")
                if page_num == 0:
                    debug_artifacts(page, "linkedin_ch_empty")
                break

            new_jobs = []
            for item in raw:
                job_url = item.get("href", "")
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                title = item.get("title", "").strip()
                if not title:
                    continue

                # URL assoluto
                if job_url.startswith("/"):
                    job_url = BASE_URL + job_url
                elif not job_url.startswith("http"):
                    continue

                new_jobs.append({
                    "title":    title,
                    "company":  item.get("company", "").strip(),
                    "city":     item.get("city", "").strip(),
                    "date":     _relative_to_date(item.get("dateRaw", "")),
                    "url":      job_url,
                    "category": categorize_job(title),
                    "source":   "linkedin.ch",
                })

            if not new_jobs:
                print(f"  [linkedin.ch] Nessun nuovo annuncio — stop")
                break

            all_jobs.extend(new_jobs)
            print(f"  [linkedin.ch] {len(new_jobs)} nuovi (tot. {len(all_jobs)})")
            human_delay(2.5, 5.0)

        print(f"  [linkedin.ch] {len(all_jobs)} annunci trovati")
        return all_jobs
    finally:
        try:
            page.close()
        except Exception:
            pass
        if auth_ctx:
            try:
                auth_ctx.close()
            except Exception:
                pass
