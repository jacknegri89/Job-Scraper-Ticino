"""
Monster Svizzera — DISABILITATO.

www.monster.ch reindirizza a monster.com/de (portale tedesco globale).
Il dominio svizzero non esiste più come portale indipendente: nessun annuncio
recuperabile. La funzione restituisce lista vuota senza aprire il browser.
"""


def scrape_monster_ch(context) -> list:  # noqa: ARG001
    from scrapers.site_report import run_report
    print("  [monster.ch] Portale non disponibile (redirect a monster.com/de) — skip")
    run_report.set_status("monster.ch", "disabled",
                          "monster.ch reindirizza a monster.com/de — nessun portale CH")
    return []
