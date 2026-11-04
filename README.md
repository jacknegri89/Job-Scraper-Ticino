# Job Scraper Ticino

[![CI](https://github.com/jacknegri89/Job-Scraper-Ticino/actions/workflows/ci.yml/badge.svg)](https://github.com/jacknegri89/Job-Scraper-Ticino/actions/workflows/ci.yml)

Job Scraper Ticino collects job postings from Swiss portals, filters them
for eight supported municipalities in the Mendrisio district, enriches them with optional AI analysis, and writes
an interactive `index.html` dashboard.

The project is designed for local use. Generated outputs, browser sessions, and
personal configuration stay out of Git.

## Install

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows; on macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`requirements.txt` is the required dependency file for this project. Keep it in
sync when runtime or test dependencies change.
Chromium runs with its sandbox enabled. On Linux, the system must support the
Chromium sandbox; configure the host if browser startup reports a sandbox error.

## Quickstart

Create your local config from the template:

```powershell
copy user_config.example.py user_config.py
```

On macOS/Linux, use `cp user_config.example.py user_config.py` instead. Run
commands from the project directory: the cache and dashboard use the current
working directory.
The optional `setup_task_scheduler.bat` creates a Windows scheduled task but
does not set its working directory. Check the task configuration before using
it, or generated files may be written outside the project directory.

Edit `user_config.py` with your home coordinates, dashboard home-city label, and
AI profile. `user_config.py` is local and ignored by Git; commit changes to
`user_config.example.py` only when the shared template needs to change.
The example coordinates are placeholders: replace them before using distance
estimates. If `user_config.py` is absent, fallback coordinates and a generic AI
profile are used instead of your personal settings.

Run a full scan:

```bash
python main.py
```

After a successful run, open `index.html` in a browser. The dashboard includes
live search, category filters, an AI match filter, distance sorting, estimated
salary details, and links to the original postings.

## CLI Modes

```bash
python main.py
```
Run the complete workflow: scrape, fetch descriptions, run AI analysis when
configured, save the cache, generate `index.html`, and open it.

```bash
python main.py --scan-only
```
Scan sites and write `scan_report.json`, without fetching descriptions, AI
analysis, dashboard generation, or changing the jobs cache.

```bash
python main.py --dry-run
```
Probe each site quickly for reachability, cookie banners, login gates, and basic
selectors.

```bash
python main.py --only jobs.ch,indeed
```
Limit the run to selected site keys. Partial runs merge with the existing cache
where possible.

```bash
python main.py --headless
```
Run Chromium without a visible browser window.

```bash
python main.py --timeout 45000
```
Override the navigation timeout in milliseconds.

```bash
python main.py --auth linkedin
```
Open a manual login flow for supported sites and save the browser session for
later runs. The LinkedIn scraper uses its saved session. The Indeed scraper
currently runs in public mode and does not use the session saved by `--auth indeed`.

```bash
python main.py --reanalyze
```
Reuse `jobs_cache.json`, analyze jobs that do not yet have an AI result, and
regenerate the dashboard without scraping. Existing AI results are reused, even
if the candidate profile has changed; this option does not force reanalysis.

## Architecture

```text
main.py                  CLI entry point and workflow orchestration
job_filter.py            Ticino city filtering, URL normalization, deduping, categories
distance_calculator.py   Offline haversine distance from configured HOME_CITY
salary_calculator.py     Swiss gross salary to estimated Italian net salary
ai_analyzer.py           Optional OpenAI analysis and salary estimate enrichment
dashboard_builder.py     Generates the interactive HTML dashboard
requirements.txt         Required Python dependency list
user_config.example.py   Shared local-config template
user_config.py           Local ignored personal configuration

scrapers/
  __init__.py            Browser setup, retry helper, description fetching
  settings.py            Timeouts, headless mode, retry settings
  page_guard.py          Cookie, login, and blocking detection
  session.py             Manual auth flow and saved browser sessions
  site_report.py         Site status records, scan_report.json, debug artifacts
  *_ch.py                One scraper module per supported portal

tests/
  test_html_generator.py Dashboard generation smoke tests
  test_filters.py        Filtering and normalization tests
  test_distance.py       Distance tests
  test_tax_calculator.py Salary/tax tests
  test_robustness.py     Retry and guard behavior tests
  test_scan_regressions.py Cache, pagination, and AI result regression tests
```

A full run follows this flow:

1. Site scrapers collect raw jobs.
2. `job_filter.filter_jobs` keeps supported Ticino locations and removes duplicates.
3. Cached descriptions and AI results are reused when possible.
4. Missing descriptions and contact emails are fetched.
5. `ai_analyzer.analyze_jobs` enriches jobs when `OPENAI_API_KEY` is available.
6. `dashboard_builder.generate_html` writes `index.html`.

## Configuration

Local personal configuration lives in `user_config.py`, copied from
`user_config.example.py`.

| Name | Where | Purpose |
|------|-------|---------|
| `HOME_LAT` | `user_config.py` | Home latitude for distance estimates |
| `HOME_LNG` | `user_config.py` | Home longitude for distance estimates |
| `HOME_CITY` | `user_config.py` | Dashboard label used in `From {HOME_CITY}` |
| `CANDIDATE_PROFILE` | `user_config.py` | Profile text sent to the AI analyzer |
| `OPENAI_API_KEY` | environment | Enables OpenAI analysis |
| `SCRAPER_HEADLESS` | environment | `1` runs the browser headlessly |
| `SCRAPER_TIMEOUT_MS` | environment | Default navigation timeout |
| `SCRAPER_ATTEMPTS` | environment | Retry attempts per scraper, capped by code |

The location filter currently accepts Chiasso, Mendrisio, Stabio, Balerna,
Coldrerio, Morbio Inferiore, Novazzano, and Riva San Vitale. Search terms for
jobs.ch and the municipality list are defined in `job_filter.py`; editing them
requires changing code. The other portals use their own search strategies.
Distances are straight-line estimates, not travel distances or times.
Unknown posting dates remain blank; relative dates supplied by portals are
approximate and can change when an announcement is refreshed.

Generated files are intentionally ignored:

| Path | Contents |
|------|----------|
| `index.html` | Generated dashboard |
| `jobs_cache.json` | Cached jobs, descriptions, emails, and AI results |
| `jobs_cache.partial.json` | Results recovered from an interrupted scan |
| `scan_report.json` | Per-site scan status |
| `debug/` | Debug screenshots and page snapshots |
| `profile/` | Saved browser auth sessions and cookies |

Results from sources that fail, are blocked, return an ambiguous empty result,
or complete only partially are preserved from the previous cache. These entries
may no longer be current; check the per-source status in `scan_report.json`.
An interrupted scan does not replace the main cache.

## Testing

Run the focused dashboard tests:

```bash
python -m pytest tests/test_html_generator.py -q
```

Compile the dashboard builder:

```bash
python -m py_compile dashboard_builder.py
```

Run the full test suite:

```bash
python -m pytest tests/ -v
```

The test suite covers filtering, city and URL normalization, dashboard HTML,
distance calculation, salary calculation, retries, page guard behavior, cache
preservation, jobs.ch pagination, and AI result validation. Tests do not verify
that live portals currently work or measure scraping performance.

## Salary estimates

When AI analysis supplies an estimated gross salary, the dashboard calculates
an indicative net amount using the assumptions in `salary_calculator.py`.
Neither figure is a verified salary offer or a personalized tax calculation.
Check the original posting and applicable rules before making decisions.

## Privacy

Do not commit `user_config.py`; it contains personal coordinates and the AI
profile. Use `user_config.example.py` as the shared template.

Do not commit generated caches, browser profiles, debug screenshots, or HTML
outputs. They can contain personal settings, cookies, contact emails, scraped
content, or transient site data.

Set `OPENAI_API_KEY` as an environment variable instead of writing it into source
files. Review `jobs_cache.json` locally before sharing any logs or artifacts,
because AI prompts and scraped descriptions may include personal or copyrighted
content from job portals.

## Legal Notes

The scraper reads public pages and does not create fake accounts. For portals
that require a user session, use the manual `--auth` flow and follow the portal's
terms. Site structure and access controls can change; check `scan_report.json`
and `debug/` when a scraper starts returning empty or blocked results.

## License

Released under the [MIT License](./LICENSE) © 2026 Giacomo Negri.
