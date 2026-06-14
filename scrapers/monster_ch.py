"""
Monster Switzerland - DISABLED.

www.monster.ch redirects to monster.com/de, the global German portal.
The Swiss domain is no longer an independent portal, so no jobs are
recoverable. This function returns an empty list without opening the browser.
"""


def scrape_monster_ch(context: object) -> list[dict[str, str]]:  # noqa: ARG001
    from scrapers.site_report import run_report
    print("  [monster.ch] Portal unavailable (redirects to monster.com/de) - skip")
    run_report.set_status("monster.ch", "disabled",
                          "monster.ch redirects to monster.com/de - no CH portal")
    return []
