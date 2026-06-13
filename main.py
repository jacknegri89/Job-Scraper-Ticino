# Entry point dello scraper lavoro Ticino.
#
# Uso rapido:
#   python main.py                  scansione completa + descrizioni + AI + HTML
#   python main.py --scan-only      solo scansione siti + report (no descrizioni/AI/HTML)
#   python main.py --dry-run        probe veloce (raggiungibilità, cookie, login gate)
#   python main.py --only a,b       limita ai siti indicati (es. --only indeed,linkedin)
#   python main.py --headless       browser nascosto (default: visibile)
#   python main.py --auth linkedin  login MANUALE nel browser; salva la sessione
#   python main.py --reanalyze      rifà solo l'analisi AI dalla cache
#   python -m pytest tests/ -v      esegue tutti i test
#
# MAPPA DEL PROGETTO
#   main.py                    ← sei qui: CLI, loop sui siti, fasi descrizioni/AI/HTML
#   job_filter.py              comuni ammessi, normalizzazione città/URL, dedup, categorie
#   distance_calculator.py     km da Barlassina per ogni comune (haversine, offline)
#   salary_calculator.py       stima netto frontaliero (lordo CH → netto IT)
#   ai_analyzer.py             analisi annunci con OpenAI (adatto/non adatto, stipendio)
#   dashboard_builder.py       genera index.html (dashboard dark, ricerca, filtri)
#   scrapers/__init__.py       browser anti-detection, retry, fetch_description
#   scrapers/settings.py       timeout/headless/tentativi (override da env SCRAPER_*)
#   scrapers/page_guard.py     cookie banner per dominio, rilevamento login/captcha
#   scrapers/session.py        login manuale (--auth) e sessioni salvate in profile/
#   scrapers/site_report.py    stato per sito, scan_report.json, screenshot di debug
#   scrapers/<sito>.py         uno scraper per portale; ritorna list[dict]:
#                              title/company/city/date/url/category/source
#
# FLUSSO DI UN RUN COMPLETO
#   1. scrapers/<sito>.py  raccoglie annunci grezzi           (raw_jobs)
#   2. job_filter.filter_jobs  filtra comuni ammessi + dedup  (valid)
#   3. _reuse_previous_data recupera desc/AI dalla cache      (non si ripaga)
#   4. fetch_description    scarica testo annuncio + email
#   5. ai_analyzer          analisi AI (adatto/non adatto + stipendio stimato)
#   6. dashboard_builder    genera index.html, salva jobs_cache.json
#
# Stati nel scan_report.json:
#   ok / ok_partial / empty / requires_auth / requires_manual_login /
#   blocked / timeout / network_error / browser_closed / selector_broken /
#   disabled / error

import argparse
import json
import sys
import time
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from scrapers import create_browser_context, save_session, fetch_description, SESSION_FILE
from scrapers.site_report import run_report, classify_exception, ScrapeError
from scrapers.page_guard import dismiss_cookies, detect_auth_gate, detect_block
from scrapers import settings as cfg
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.carriera_ch import scrape_carriera_ch
from scrapers.gigroup_ch import scrape_gigroup_ch
from scrapers.randstad_ch import scrape_randstad_ch
from scrapers.orienta_ch import scrape_orienta_ch
from scrapers.jobscout24_ch import scrape_jobscout24_ch
from scrapers.indeed_ch import scrape_indeed_ch
from scrapers.monster_ch import scrape_monster_ch
from scrapers.adecco_ch import scrape_adecco_ch
from scrapers.manpower_ch import scrape_manpower_ch
from scrapers.frontaliereticino_ch import scrape_frontaliereticino_ch
from scrapers.linkedin_ch import scrape_linkedin_ch
from job_filter import filter_jobs, is_valid_job, normalize_url
from dashboard_builder import generate_html
from ai_analyzer import analyze_jobs

CACHE_FILE = Path("jobs_cache.json")

# Le pipe Windows usano cp1252: senza questo, un solo carattere non
# codificabile (box-drawing, ✓, titoli di annunci esotici) ucciderebbe
# l'intero run con UnicodeEncodeError. I non codificabili diventano "?".
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

# (etichetta log, chiave sito nel report, funzione)
_SCRAPERS = [
    ("JOBS.CH",               "jobs.ch",               scrape_jobs_ch),
    ("CARRIERA.CH",           "carriera.ch",           scrape_carriera_ch),
    ("GI GROUP CH",           "gigroup.ch",            scrape_gigroup_ch),
    ("RANDSTAD CH",           "randstad.ch",           scrape_randstad_ch),
    ("ORIENTA CH",            "orienta.ch",            scrape_orienta_ch),
    ("JOBSCOUT24 CH",         "jobscout24.ch",         scrape_jobscout24_ch),
    ("INDEED CH",             "indeed.ch",             scrape_indeed_ch),
    ("MONSTER CH",            "monster.ch",            scrape_monster_ch),
    ("ADECCO CH",             "adecco.ch",             scrape_adecco_ch),
    ("MANPOWER CH",           "manpower.ch",           scrape_manpower_ch),
    ("FRONTALIERETICINO CH",  "frontaliereticino.ch",  scrape_frontaliereticino_ch),
    ("LINKEDIN CH",           "linkedin.ch",           scrape_linkedin_ch),
]

# URL + selettore "pagina pronta" per il probe --dry-run.
# monster.ch non è incluso (disabilitato), frontaliereticino è HTTP puro.
_PROBES = {
    "jobs.ch":        ("https://www.jobs.ch/en/vacancies/?term=operaio&location=ticino",
                       'a[data-cy="job-link"]'),
    "carriera.ch":    ("https://www.carriera.ch/offerte/annunci-offerte-lavoro_0_0_0.html",
                       "tr td a"),
    "gigroup.ch":     ("https://ch.gigroup.com/it/posizioni-aperte/?npage=1",
                       ".ggp-job-item"),
    "randstad.ch":    ("https://www.randstad.ch/it/lavoro/re-ticino/",
                       'a[href*="/it/lavoro/"]'),
    "orienta.ch":     ("https://www.orienta.ch/it/orienta-job/offerte-di-lavoro.html?page=1",
                       "article a[href*='/offerta-di-lavoro/']"),
    "jobscout24.ch":  ("https://www.jobscout24.ch/de/jobs/ticino/?p=1",
                       'a[href^="/de/job/"]'),
    "indeed.ch":      ("https://ch.indeed.com/jobs?q=&l=Ticino&radius=50",
                       "a[data-jk]"),
    "adecco.ch":      ("https://www.adecco.com/it-ch/trovare-lavoro?jobsearch-title=&location=Ticino",
                       "article[class*='JobSearch_job-search-card']"),
    "manpower.ch":    ("https://www.manpower.ch/it/trova-lavoro/citta/lugano",
                       'a[href*="/it/job/"]'),
    "linkedin.ch":    ("https://www.linkedin.com/jobs/search/?keywords=&location=Ticino%2C+Switzerland",
                       '[class*="base-card"]'),
}


# ──────────────────────────────────────────────────────────────
# Barra di avanzamento
# ──────────────────────────────────────────────────────────────

def _fmt_s(s: float) -> str:
    """Secondi → '2m 05s' oppure '48s'."""
    s = int(s)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m {sec:02d}s"
    h, mn = divmod(m, 60)
    return f"{h}h {mn:02d}m"


def _print_bar(done: int, total: int, elapsed: float,
               step_times: list, phase: str = "Siti", label: str = "") -> None:
    """Stampa una riga divisore + barra di avanzamento con ETA."""
    pct    = done / total if total else 0
    w      = 38
    filled = int(w * pct)
    bar    = "#" * filled + "-" * (w - filled)

    if step_times and done < total:
        avg = sum(step_times) / len(step_times)
        eta = f"~{_fmt_s(avg * (total - done))}"
    elif done >= total:
        eta = "completato"
    else:
        eta = "..."

    lbl = f"  >> {label}" if label else ""
    print(f"\n{'-' * 64}")
    print(f"  {phase}: [{bar}] {int(pct * 100):3d}% ({done}/{total})"
          f"  {_fmt_s(elapsed)} trascorsi  ETA {eta}{lbl}")
    print(f"{'-' * 64}\n")


# ──────────────────────────────────────────────────────────────
# Browser helpers
# ──────────────────────────────────────────────────────────────

def _context_alive(context) -> bool:
    """True se il BrowserContext Playwright è ancora utilizzabile."""
    try:
        _ = context.pages
        return True
    except Exception:
        return False


def _revive_context(p, browser, context):
    """Ricrea browser+context dopo una morte improvvisa (ritorna i nuovi)."""
    print("[WARN] Contesto browser chiuso — ricreazione in corso...")
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()      # lo stato salvato potrebbe essere corrotto
    try:
        browser.close()
    except Exception:
        pass
    return create_browser_context(p)


# ──────────────────────────────────────────────────────────────
# Cache helpers
# ──────────────────────────────────────────────────────────────

def _save_cache(jobs: list) -> None:
    CACHE_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CACHE] {len(jobs)} annunci salvati in {CACHE_FILE}")


def _merge_with_cache(new_jobs: list, scanned_sources: set) -> list:
    """
    Per i run parziali (--only): fonde i nuovi annunci con la cache esistente,
    sostituendo SOLO le fonti scansionate. Le altre fonti restano intatte.
    """
    if not CACHE_FILE.exists():
        return new_jobs
    try:
        old = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return new_jobs
    kept = [j for j in old if j.get("source") not in scanned_sources]
    if kept:
        print(f"[CACHE] Merge: {len(kept)} annunci di altre fonti preservati"
              f" + {len(new_jobs)} nuovi")
    return kept + new_jobs


def _load_cache() -> list:
    if not CACHE_FILE.exists():
        print("[ERRORE] Nessuna cache trovata (jobs_cache.json). Esegui prima: python scraper.py")
        sys.exit(1)
    jobs = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    print(f"[CACHE] Caricati {len(jobs)} annunci da {CACHE_FILE} (salvata il {mtime})")
    return jobs


def _reuse_previous_data(valid: list) -> int:
    """
    Copia descrizione/email/analisi LLM dalla cache del run precedente
    sugli annunci appena scrapati (match per URL normalizzato).
    """
    if not CACHE_FILE.exists():
        return 0
    try:
        old_jobs = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0

    old_by_url = {}
    for j in old_jobs:
        key = normalize_url(j.get("url", ""))
        if key:
            old_by_url[key] = j

    reused = 0
    for job in valid:
        old = old_by_url.get(normalize_url(job.get("url", "")))
        if not old:
            continue
        if old.get("description") and not job.get("description"):
            job["description"] = old["description"]
            job["email"]       = old.get("email", "")
        if old.get("llm_adatto") is not None:
            job["llm_adatto"]          = old["llm_adatto"]
            job["llm_motivo"]          = old.get("llm_motivo", "")
            job["llm_descrizione"]     = old.get("llm_descrizione", "")
            job["llm_stipendio_lordo"] = old.get("llm_stipendio_lordo")
        reused += 1
    return reused


# ──────────────────────────────────────────────────────────────
# Selezione siti (--only)
# ──────────────────────────────────────────────────────────────

def _select_scrapers(only: str):
    if not only:
        return _SCRAPERS
    wanted = [w.strip().lower() for w in only.split(",") if w.strip()]
    sel = [(lbl, site, fn) for lbl, site, fn in _SCRAPERS
           if any(w in site for w in wanted)]
    if not sel:
        print(f"[ERRORE] --only {only!r} non corrisponde a nessun sito.")
        print("Siti disponibili:", ", ".join(s for _, s, _ in _SCRAPERS))
        sys.exit(1)
    return sel


# ──────────────────────────────────────────────────────────────
# Dry-run: probe veloce di ogni sito
# ──────────────────────────────────────────────────────────────

def _probe_frontaliereticino(t0: float) -> None:
    """Probe del sito senza browser: GET dell'indice JSON sul CDN."""
    import urllib.request
    site = "frontaliereticino.ch"
    try:
        req = urllib.request.Request(
            "https://cdn.frontaliereticino.ch/data/jobs-it-index.json",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            n = len(json.loads(r.read().decode("utf-8")))
        run_report.finish(site, 0, time.perf_counter() - t0,
                          status="ok", reason=f"indice JSON ok ({n} record)")
        print(f"  [{site}] ok — indice JSON con {n} record")
    except Exception as e:
        status, reason = classify_exception(e)
        run_report.finish(site, 0, time.perf_counter() - t0,
                          status=status, reason=reason)
        print(f"  [{site}] {status} — {reason}")


def _probe_check_selector(page, site: str, ready_sel: str, t0: float) -> None:
    """Verifica che il selettore dei risultati esista nel DOM della pagina."""
    from scrapers.report import debug_artifacts
    try:
        # state="attached": basta la presenza nel DOM — il primo match
        # può essere un link di menu nascosto (es. Randstad)
        page.wait_for_selector(ready_sel, timeout=10_000, state="attached")
        run_report.finish(site, 0, time.perf_counter() - t0,
                          status="ok", reason="selettore risultati presente")
        print(f"  [{site}] ok")
    except Exception:
        shot = debug_artifacts(page, f"probe_{site.replace('.', '_')}")
        run_report.set_status(site, "selector_broken",
                              f"selettore {ready_sel!r} assente",
                              final_url=page.url, screenshot=shot)
        run_report.finish(site, 0, time.perf_counter() - t0)


def _probe_browser_site(context, site: str, url: str, ready_sel: str,
                        t0: float) -> None:
    """Probe via browser: apre pagina 1, chiude cookie, rileva gate/blocchi."""
    from scrapers import new_stealth_page
    from scrapers.report import debug_artifacts

    print(f"  [{site}] {url[:70]}…")
    page = new_stealth_page(context)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=cfg.PAGE_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        dismiss_cookies(page, site)

        block = detect_block(page)
        gate  = detect_auth_gate(page)
        if block:
            shot = debug_artifacts(page, f"probe_{site.replace('.', '_')}")
            run_report.set_status(site, "blocked", block,
                                  final_url=page.url, screenshot=shot)
            run_report.finish(site, 0, time.perf_counter() - t0)
        elif gate:
            shot = debug_artifacts(page, f"probe_{site.replace('.', '_')}")
            run_report.set_status(site, "requires_auth", gate,
                                  final_url=page.url, screenshot=shot)
            run_report.finish(site, 0, time.perf_counter() - t0)
        else:
            _probe_check_selector(page, site, ready_sel, t0)
    except Exception as e:
        status, reason = classify_exception(e)
        run_report.finish(site, 0, time.perf_counter() - t0,
                          status=status, reason=reason)
        print(f"  [{site}] {status} — {reason}")
    finally:
        try:
            page.close()
        except Exception:
            pass


def _dry_run(only: str = "") -> None:
    """
    Per ogni sito: apre la prima pagina, chiude i cookie, rileva login
    gate / blocchi e verifica che il selettore dei risultati esista.
    Nessuna paginazione, nessun salvataggio dati. Stato nel report.
    """
    selected = _select_scrapers(only)
    print(f"[DRY-RUN] Probe di {len(selected)} siti (timeout {cfg.PAGE_TIMEOUT_MS} ms)\n")

    with sync_playwright() as p:
        browser, context = create_browser_context(p)
        try:
            for _label, site, _fn in selected:
                t0 = time.perf_counter()

                if site == "monster.ch":
                    run_report.set_status(site, "disabled",
                                          "portale dismesso (redirect a monster.com/de)")
                    run_report.finish(site, 0, time.perf_counter() - t0,
                                      status="disabled", reason="portale dismesso")
                elif site == "frontaliereticino.ch":
                    _probe_frontaliereticino(t0)
                elif site in _PROBES:
                    url, ready_sel = _PROBES[site]
                    _probe_browser_site(context, site, url, ready_sel, t0)
                else:
                    run_report.finish(site, 0, 0, status="error",
                                      reason="nessun probe definito")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    run_report.print_table()
    run_report.save()


# ──────────────────────────────────────────────────────────────
# Scraping completo
# ──────────────────────────────────────────────────────────────

def _scrape_one_site(fn, site: str, context) -> list:
    """
    Esegue un singolo scraper registrando l'esito nel report.
    Non solleva mai: in caso di errore ritorna [] e lo stato resta nel report.
    """
    t_step = time.perf_counter()
    try:
        jobs = fn(context)
    except ScrapeError as e:
        run_report.finish(site, 0, time.perf_counter() - t_step,
                          status=e.status, reason=e.reason, attempts=e.attempts)
        return []
    except Exception as e:
        status, reason = classify_exception(e)
        run_report.finish(site, 0, time.perf_counter() - t_step,
                          status=status, reason=reason)
        return []
    run_report.finish(site, len(jobs), time.perf_counter() - t_step)
    return jobs


def _print_filter_summary(raw_jobs: list, valid: list) -> None:
    in_zona = sum(1 for j in raw_jobs if is_valid_job(j))
    print(f"[FILTER] {len(raw_jobs)} grezzi → {in_zona} nei comuni ammessi"
          f" → {len(valid)} unici dopo dedup")
    per_fonte = Counter(j.get("source", "?") for j in valid)
    print("[FILTER] Per fonte: "
          + " · ".join(f"{s}:{n}" for s, n in sorted(per_fonte.items())))


def _download_descriptions(context, valid: list) -> None:
    """Scarica descrizione ed email per gli annunci che non le hanno già."""
    da_scaricare = [j for j in valid if not j.get("description")]
    if not da_scaricare:
        return

    n_desc   = len(da_scaricare)
    n_cached = len(valid) - n_desc
    t_desc   = time.perf_counter()
    desc_times: list[float] = []

    print(f"\n=== DESCRIZIONI ({n_desc} da scaricare, {n_cached} da cache) ===")
    for idx, job in enumerate(da_scaricare):
        _print_bar(idx, n_desc, time.perf_counter() - t_desc, desc_times,
                   phase="Descrizioni", label=job.get("title", "")[:40])

        t_d = time.perf_counter()
        details = fetch_description(context, job.get("url", ""))
        job["description"] = details["description"]
        job["email"]       = details["email"]
        desc_times.append(time.perf_counter() - t_d)

        email_tag = " [email]" if details["email"] else ""
        print(f"[DESC] {idx + 1}/{n_desc} — "
              f"{job.get('title', '')[:50]}{email_tag}  ({_fmt_s(desc_times[-1])})")

    _print_bar(n_desc, n_desc, time.perf_counter() - t_desc,
               desc_times, phase="Descrizioni")


def _run_scrape(only: str = "", scan_only: bool = False) -> list:
    """Esegue scraping completo (+ descrizioni se non scan_only). Ritorna la lista valida."""
    selected   = _select_scrapers(only)
    raw_jobs   = []
    valid      = []
    completed  = False
    n_total    = len(selected)
    t_start    = time.perf_counter()
    step_times: list[float] = []

    with sync_playwright() as p:
        browser, context = create_browser_context(p)
        try:
            for i, (name, site, fn) in enumerate(selected):
                if not _context_alive(context):
                    browser, context = _revive_context(p, browser, context)

                _print_bar(i, n_total, time.perf_counter() - t_start,
                           step_times, label=name)
                print(f"=== {name} ===")

                t_step = time.perf_counter()
                jobs = _scrape_one_site(fn, site, context)
                raw_jobs.extend(jobs)

                step_times.append(time.perf_counter() - t_step)
                print(f"  +- {len(jobs)} annunci in {_fmt_s(step_times[-1])}")

            _print_bar(n_total, n_total, time.perf_counter() - t_start, step_times)

            valid = filter_jobs(raw_jobs)
            _print_filter_summary(raw_jobs, valid)

            riusati = _reuse_previous_data(valid)
            if riusati:
                print(f"[CACHE] Dati riusati dal run precedente per {riusati} annunci"
                      " (descrizioni/analisi già pagate)")

            if not scan_only:
                _download_descriptions(context, valid)

            completed = True
        except KeyboardInterrupt:
            print("\n[STOP] Interrotto dall'utente — salvo quanto raccolto finora")
            if not valid:
                valid = filter_jobs(raw_jobs)
        except Exception as e:
            print(f"[ERRORE CRITICO] {e}")
            if not valid:
                valid = filter_jobs(raw_jobs)
        finally:
            save_session(context)
            try:
                browser.close()
            except Exception:
                pass

    run_report.print_table()
    run_report.save()

    # Run parziale (--only): le fonti non scansionate restano in cache
    if only:
        valid = _merge_with_cache(valid, {site for _, site, _ in selected})

    if valid and completed:
        _save_cache(valid)
    elif valid:
        # Scansione incompleta: MAI sovrascrivere la cache buona
        partial = Path("jobs_cache.partial.json")
        partial.write_text(json.dumps(valid, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        print(f"[CACHE] Scansione incompleta — {len(valid)} annunci salvati in"
              f" {partial} (cache principale non toccata)")

    return valid


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def _parse_args():
    ap = argparse.ArgumentParser(description="Scraper lavoro Ticino — frontalieri")
    ap.add_argument("--reanalyze", action="store_true",
                    help="rifà solo l'analisi AI dalla cache (no scraping)")
    ap.add_argument("--scan-only", action="store_true",
                    help="solo scansione siti + report (no descrizioni/AI/HTML)")
    ap.add_argument("--dry-run", action="store_true",
                    help="probe veloce di ogni sito senza scraping completo")
    ap.add_argument("--only", default="",
                    help="limita ai siti indicati, es. --only indeed,linkedin")
    ap.add_argument("--headless", action="store_true",
                    help="browser nascosto (default: visibile)")
    ap.add_argument("--timeout", type=int, default=0, metavar="MS",
                    help=f"timeout navigazione in ms (default {cfg.PAGE_TIMEOUT_MS})")
    ap.add_argument("--auth", default="", metavar="SITO",
                    help="login manuale e salvataggio sessione (es. --auth linkedin)")
    return ap.parse_args()


def main():
    args  = _parse_args()
    start = datetime.now()

    # Override di configurazione da CLI
    if args.headless:
        cfg.HEADLESS = True
    if args.timeout > 0:
        cfg.PAGE_TIMEOUT_MS = args.timeout

    # Modalità login manuale: nessuno scraping
    if args.auth:
        from scrapers.session import run_auth_flow
        with sync_playwright() as p:
            ok = run_auth_flow(p, args.auth.strip().lower())
        sys.exit(0 if ok else 1)

    if args.dry_run:
        print(f"[START] {start.strftime('%d/%m/%Y %H:%M')} — dry-run")
        _dry_run(args.only)
        return

    if args.reanalyze:
        print(f"[REANALYZE] {start.strftime('%d/%m/%Y %H:%M')} — rianalisi AI dalla cache")
        valid = _load_cache()
    else:
        print(f"[START] {start.strftime('%d/%m/%Y %H:%M')}"
              + (" — scan-only" if args.scan_only else ""))
        valid = _run_scrape(args.only, scan_only=args.scan_only)
        if args.scan_only:
            elapsed = int((datetime.now() - start).total_seconds())
            print(f"[DONE] Scansione completata in {_fmt_s(elapsed)}."
                  " Report: scan_report.json")
            return

    valid = analyze_jobs(valid)

    if valid:
        _save_cache(valid)

    if valid and not any(j.get("llm_adatto") is not None for j in valid):
        print("[HINT] Per rifare solo l'analisi AI (senza riscraping):"
              " python scraper.py --reanalyze")

    generate_html(valid)

    elapsed = int((datetime.now() - start).total_seconds())
    print(f"[DONE] Completato in {_fmt_s(elapsed)}.")
    html_path = Path("index.html").resolve()
    webbrowser.open(html_path.as_uri())


if __name__ == "__main__":
    main()
