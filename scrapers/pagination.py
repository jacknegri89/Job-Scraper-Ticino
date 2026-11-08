"""The page loop shared by portals that list jobs over several pages.

Two rules that every such scraper needs:
- A page that fails after some listings were read ends the loop and the source is reported
  as partial. The listings already collected are kept. A failure before any listing was
  read is raised, so the normal retry logic can try again.
- When a page returns nothing, a block or a login wall is looked for. If there is one it is
  reported, never bypassed, and no further page of that portal is requested in this scan.
"""

from collections.abc import Callable, Iterable
from typing import Any

from scrapers.page_guard import detect_auth_gate, detect_block
from scrapers.site_report import debug_artifacts, run_report


def collect_pages(
    page: Any,
    site: str,
    page_numbers: Iterable[int],
    add_page: Callable[[int], bool],
    collected_jobs: list,
) -> None:
    """Call add_page(page_number) until it returns False (no more results) or a page fails."""
    for page_number in page_numbers:
        try:
            has_more = add_page(page_number)
        except Exception as error:
            if not collected_jobs:
                raise
            print(f"  [{site}] page {page_number} failed ({type(error).__name__}); keeping {len(collected_jobs)} jobs")
            run_report.set_status(site, "ok_partial", f"page {page_number} could not be read ({type(error).__name__})")
            return
        if not has_more:
            report_gate_if_any(page, site)
            return


def report_gate_if_any(page: Any, site: str) -> bool:
    """Report a block or login wall on this page. Returns True when one was found."""
    try:
        block_reason = detect_block(page)
        auth_reason = detect_auth_gate(page)
    except Exception:
        return False
    if block_reason:
        screenshot = debug_artifacts(page, f"{site.replace('.', '_')}_gate")
        run_report.set_status(site, "blocked", block_reason, final_url=_url_of(page), screenshot=screenshot)
        print(f"  [{site}] Block detected ({block_reason}) - no further pages requested")
        return True
    if auth_reason:
        run_report.set_status(site, "requires_auth", auth_reason, final_url=_url_of(page))
        print(f"  [{site}] Login required ({auth_reason}) - no further pages requested")
        return True
    return False


def _url_of(page: Any) -> str:
    try:
        return str(page.url)
    except Exception:
        return ""
