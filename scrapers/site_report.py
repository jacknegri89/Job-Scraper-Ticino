# Report strutturato della scansione: uno stato per ogni sito.
#
# Stati possibili:
#   ok                    annunci raccolti, nessun problema
#   ok_partial            annunci raccolti ma parte del sito è inaccessibile
#   empty                 sito raggiungibile ma zero annunci
#   requires_auth         contenuto dietro login
#   requires_manual_login serve la sessione: python scraper.py --auth <sito>
#   blocked               captcha / anti-bot
#   timeout               la pagina non ha risposto in tempo
#   network_error         DNS / connessione / abort
#   browser_closed        browser o pagina chiusi durante lo scraping
#   selector_broken       pagina raggiunta ma struttura DOM non riconosciuta
#   disabled              scraper disattivato di proposito (es. monster.ch)
#   error                 errore non classificato (vedi campo reason)

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

from scrapers.settings import DEBUG_DIR, REPORT_FILE


@dataclass
class SiteResult:
    site:       str
    status:     str = "ok"
    jobs:       int = 0
    duration_s: float = 0.0
    attempts:   int = 1
    reason:     str = ""
    final_url:  str = ""
    screenshot: str = ""


class RunReport:
    """Raccoglie i risultati di tutti i siti di una scansione."""

    def __init__(self):
        self._results:   dict[str, SiteResult] = {}
        self._overrides: dict[str, dict]       = {}
        self.started = datetime.now()

    def set_status(self, site: str, status: str, reason: str = "",
                   final_url: str = "", screenshot: str = "") -> None:
        # Chiamato dagli scraper quando rilevano un gate (login, captcha)
        # senza interrompere la raccolta degli annunci già trovati.
        self._overrides[site] = {
            "status": status, "reason": reason,
            "final_url": final_url, "screenshot": screenshot,
        }
        print(f"  [report] {site}: {status}" + (f" — {reason}" if reason else ""))

    def finish(self, site: str, jobs: int, duration_s: float,
               status: str = "", reason: str = "", attempts: int = 1) -> SiteResult:
        ov = self._overrides.get(site, {})
        if not status:
            status = "ok" if jobs > 0 else "empty"
        # Un override dello scraper (gate/blocco) vince sullo stato calcolato.
        # Se però ci sono annunci raccolti, lo stato diventa ok_partial.
        if ov:
            status = ov["status"]
            reason = ov["reason"] or reason
            if jobs > 0 and ov["status"] in ("requires_auth", "requires_manual_login", "blocked"):
                status = "ok_partial"
                reason = f"{ov['status']}: {ov['reason']}" if ov["reason"] else ov["status"]
        r = SiteResult(
            site=site, status=status, jobs=jobs,
            duration_s=round(duration_s, 1), attempts=attempts, reason=reason,
            final_url=ov.get("final_url", ""), screenshot=ov.get("screenshot", ""),
        )
        self._results[site] = r
        return r

    @property
    def results(self) -> list[SiteResult]:
        return list(self._results.values())

    def save(self, path=REPORT_FILE) -> None:
        data = {
            "started":  self.started.isoformat(timespec="seconds"),
            "finished": datetime.now().isoformat(timespec="seconds"),
            "sites":    [asdict(r) for r in self.results],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[REPORT] Salvato in {path}")

    def print_table(self) -> None:
        if not self._results:
            return
        W_SITE, W_STAT = 24, 22
        print("\n" + "=" * 78)
        print(f"  {'SITO':<{W_SITE}}{'STATO':<{W_STAT}}{'JOB':>5}  {'TEMPO':>7}  NOTE")
        print("-" * 78)
        for r in self.results:
            note = r.reason[:40] if r.reason else ""
            print(f"  {r.site:<{W_SITE}}{r.status:<{W_STAT}}{r.jobs:>5}"
                  f"  {r.duration_s:>6.0f}s  {note}")
        print("=" * 78)
        n_ok = sum(1 for r in self.results if r.status in ("ok", "ok_partial"))
        print(f"  {n_ok}/{len(self.results)} siti con annunci raccolti\n")


# Istanza condivisa: gli scraper la importano per segnalare gate e blocchi.
run_report = RunReport()


def debug_artifacts(page, tag: str) -> str:
    # Salva screenshot + HTML della pagina in debug/ per diagnosi.
    # Ritorna il percorso dello screenshot ("" se non riuscito).
    # Non solleva mai: viene chiamato nei percorsi di errore.
    DEBUG_DIR.mkdir(exist_ok=True)
    shot = ""
    try:
        shot_path = DEBUG_DIR / f"{tag}.png"
        page.screenshot(path=str(shot_path))
        shot = str(shot_path)
    except Exception:
        pass
    try:
        (DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    if shot:
        print(f"  [debug] {tag}: screenshot + HTML salvati in {DEBUG_DIR}\\")
    return shot


def classify_exception(e: Exception) -> tuple[str, str]:
    """Mappa un'eccezione Playwright/di rete su (status, reason)."""
    msg  = str(e)
    low  = msg.lower()
    name = type(e).__name__.lower()

    if "timeout" in name or "timeout" in low.split("\n")[0]:
        return "timeout", msg.split("\n")[0][:160]
    if "closed" in low or "targetclosed" in name:
        return "browser_closed", msg.split("\n")[0][:160]
    if ("net::err_" in low or "err_aborted" in low or "detached" in low
            or "econn" in low or "dns" in low or "getaddrinfo" in low):
        return "network_error", msg.split("\n")[0][:160]
    return "error", f"{type(e).__name__}: {msg.split(chr(10))[0][:160]}"


class ScrapeError(Exception):
    """Sollevata dal decorator @retry quando uno scraper esaurisce i tentativi."""
    def __init__(self, status: str, reason: str, attempts: int):
        super().__init__(reason)
        self.status   = status
        self.reason   = reason
        self.attempts = attempts
