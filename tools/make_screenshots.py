"""Regenerate the images in docs/ from invented sample data.

Usage (from the project folder, with Chromium installed for Playwright):
    python tools/make_screenshots.py

Nothing here reads jobs_cache.json, user_settings.json or any other personal file: every
company, listing and link below is made up, so the pictures are safe to publish.
"""

import base64
import sys
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dashboard_builder  # noqa: E402
import distance_calculator  # noqa: E402
import setup_panel  # noqa: E402
import startup_config  # noqa: E402
from fx_rates import FxRate  # noqa: E402
from job_model import normalize_job  # noqa: E402
from playwright.sync_api import Browser, sync_playwright  # noqa: E402

DOCS_FOLDER = PROJECT_ROOT / "docs"
SAMPLE_HOME_CITY = "Como"
SAMPLE_HOME_COORDINATES = (45.81, 9.085)
SAMPLE_RATE = FxRate(1.0937, "ECB reference rate", "2026-11-06")
LAST_CHECK = "2026-11-09T08:30:00"

DASHBOARD_VIEWPORT = {"width": 1360, "height": 1100}
PANEL_VIEWPORT = {"width": 1000, "height": 1500}
SOCIAL_VIEWPORT = {"width": 1280, "height": 640}
SHARP_PIXELS = 2

SAMPLE_SOURCES = ["jobs.ch", "carriera.ch", "gigroup.ch", "randstad.ch", "orienta.ch", "jobscout24.ch", "indeed.ch",
                  "adecco.ch", "manpower.ch", "frontaliereticino.ch", "linkedin.ch", "indeed.it", "linkedin.it"]
SAMPLE_SEARCH_TERMS = ["sviluppatore", "sistemista", "help desk", "machine learning"]


def _sample_job(**fields: object) -> dict:
    job = normalize_job(fields)
    tracking = {"first_seen": "2026-11-05T07:00:00", "last_seen": LAST_CHECK, "last_verified": LAST_CHECK,
                "status": "active"}
    for name, value in tracking.items():
        job.setdefault(name, value)
    return job


def sample_jobs() -> list[dict]:
    """Invented listings that show the states the dashboard knows."""
    return [
        _sample_job(
            title="Junior Python developer", company="Sample Software Srl", city="Monza MB", date="2026-11-08",
            url="https://example.com/jobs/1", source="indeed.it", salary_text="28.000 € - 32.000 € all'anno",
            description=("We are looking for a junior developer who will work with our team on the services behind "
                         "our web platform. | You will write and test Python code, and you will learn from the "
                         "people who review it. | Permanent contract after a trial period."),
            ai_suitable=True, ai_reason="Junior role that asks for projects, not years of experience."),
        _sample_job(
            title="Sistemista Linux", company="Esempio Servizi Spa", city="Milano", date="2026-11-07",
            url="https://example.com/jobs/2", source="linkedin.it",
            description=("Gestione di server Linux, backup e monitoraggio per i clienti della regione. | "
                         "Contratto a tempo indeterminato, lavoro ibrido con due giorni in sede.")),
        _sample_job(
            title="IT support technician", company="Example Logistics SA", city="Chiasso", date="2026-11-06",
            url="https://example.com/jobs/3", source="jobs.ch",
            description=("Supporto di primo livello per il personale del magazzino: computer, stampanti e "
                         "account. | Salario CHF 4'200 al mese lordi, 13 mensilità.")),
        _sample_job(
            title="Data engineer", company="Demo Analytics Srl", city="Como", date="2026-11-05",
            url="https://example.com/jobs/4", source="indeed.it",
            sources=[{"source": "indeed.it", "url": "https://example.com/jobs/4"},
                     {"source": "linkedin.it", "url": "https://example.com/jobs/4b"}],
            description="Pipeline di dati in Python e SQL per i report dei clienti.",
            ai_suitable=True, ai_reason="Python and SQL match the profile.",
            ai_salary={"amount": 30000, "currency": "EUR", "period": "year"}),
        _sample_job(
            title="Senior backend developer", company="Prova Systems SA", city="Mendrisio", date="2026-10-20",
            url="https://example.com/jobs/5", source="jobscout24.ch", status="cached_source_unavailable",
            status_reason="jobscout24.ch could not be read completely (blocked)",
            last_verified="2026-10-30T08:00:00"),
        _sample_job(
            title="Web developer internship", company="Esempio Digitale Srl", city="Lombardia", date="2026-10-05",
            url="https://example.com/jobs/6", source="indeed.it", status="possibly_expired",
            status_reason="not seen for 20 days", last_verified="2026-10-19T08:00:00",
            salary_text="800 € al mese"),
    ]


def _use_sample_home() -> None:
    distance_calculator._HOME_COORDINATES = SAMPLE_HOME_COORDINATES
    dashboard_builder.HOME_CITY = SAMPLE_HOME_CITY


def _screenshot_dashboard(browser: Browser, dashboard_file: Path) -> None:
    for color_scheme in ("light", "dark"):
        context = browser.new_context(viewport=DASHBOARD_VIEWPORT, device_scale_factor=SHARP_PIXELS,
                                      color_scheme=color_scheme)
        page = context.new_page()
        page.goto(dashboard_file.as_uri())
        page.screenshot(path=str(DOCS_FOLDER / f"dashboard-{color_scheme}.png"))
        context.close()


def _screenshot_panel(browser: Browser) -> None:
    settings = startup_config.default_settings(SAMPLE_SOURCES, SAMPLE_SEARCH_TERMS)
    settings.update(home_city=SAMPLE_HOME_CITY, home_lat=SAMPLE_HOME_COORDINATES[0],
                    home_lng=SAMPLE_HOME_COORDINATES[1], radius_km=30, categories=["tech"],
                    sources=["indeed.it", "linkedin.it", "jobs.ch", "indeed.ch"])
    server = setup_panel.LocalPanelServer(settings, set(SAMPLE_SOURCES))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        context = browser.new_context(viewport=PANEL_VIEWPORT, device_scale_factor=SHARP_PIXELS, color_scheme="light")
        page = context.new_page()
        page.goto(f"http://{server.host}/{server.token}")
        page.screenshot(path=str(DOCS_FOLDER / "panel.png"))
        context.close()
    finally:
        server.shutdown()
        server.server_close()


def _first_card_picture(browser: Browser, dashboard_file: Path) -> str:
    context = browser.new_context(viewport=DASHBOARD_VIEWPORT, device_scale_factor=SHARP_PIXELS, color_scheme="light")
    page = context.new_page()
    page.goto(dashboard_file.as_uri())
    card_picture = page.locator("article.card").first.screenshot()
    context.close()
    return base64.b64encode(card_picture).decode("ascii")


def _social_preview_html(card_picture_base64: str) -> str:
    """The picture shown when the repository link is shared: the name, one line and one sample card."""
    return f"""<html><body style="margin:0;width:1280px;height:640px;background:#F1F3F4;color:#14181C;
font-family:'Segoe UI',system-ui,Arial,sans-serif;overflow:hidden;position:relative">
<div style="position:absolute;left:0;top:0;bottom:0;width:14px;background:#0B6B5B"></div>
<div style="position:absolute;left:72px;top:150px;width:470px">
<div style="font-size:76px;line-height:1;font-weight:700">JobScraper</div>
<div style="margin-top:26px;font-size:28px;line-height:1.35;color:#3F474F">Job listings for Lombardy and Ticino,
in one private dashboard.</div>
<div style="margin-top:34px;font-size:20px;color:#5A636D">Python · Playwright · runs on your computer</div></div>
<img src="data:image/png;base64,{card_picture_base64}" alt="" style="position:absolute;left:590px;top:50%;
transform:translateY(-50%);width:640px;border:1px solid #DADFE3;border-radius:8px;
box-shadow:0 18px 44px rgba(20,24,28,.18)">
</body></html>"""


def _screenshot_social_preview(browser: Browser, dashboard_file: Path) -> None:
    card_picture = _first_card_picture(browser, dashboard_file)
    context = browser.new_context(viewport=SOCIAL_VIEWPORT, device_scale_factor=1)
    page = context.new_page()
    page.set_content(_social_preview_html(card_picture))
    page.screenshot(path=str(DOCS_FOLDER / "social-preview.png"))
    context.close()


def main() -> None:
    _use_sample_home()
    with tempfile.TemporaryDirectory() as temporary_folder:
        dashboard_file = Path(temporary_folder) / "index.html"
        dashboard_builder.generate_html(sample_jobs(), dashboard_file, fx_rate=SAMPLE_RATE)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            _screenshot_dashboard(browser, dashboard_file)
            _screenshot_panel(browser)
            _screenshot_social_preview(browser, dashboard_file)
            browser.close()
    print(f"Images written to {DOCS_FOLDER}")


if __name__ == "__main__":
    main()
