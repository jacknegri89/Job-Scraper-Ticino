# Job Scraper Ticino

Job Scraper Ticino collects public job postings from Swiss portals, filters them
for the Mendrisio district, enriches them with optional AI analysis, and writes
an interactive `index.html` dashboard.

The project is designed for local use. Generated outputs, browser sessions, and
personal configuration stay out of Git.

## Install

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`requirements.txt` is the required dependency file for this project. Keep it in
sync when runtime or test dependencies change.

## Quickstart

Create your local config from the template:

```bash
copy user_config.example.py user_config.py
```

Edit `user_config.py` with your home coordinates, dashboard home-city label, and
AI profile. `user_config.py` is local and ignored by Git; commit changes to
`user_config.example.py` only when the shared template needs to change.

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
analysis, or dashboard generation.

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
later runs.

```bash
python main.py --reanalyze
```
Reuse `jobs_cache.json` and rerun only the AI analysis.

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

Generated files are intentionally ignored:

| Path | Contents |
|------|----------|
| `index.html` | Generated dashboard |
| `jobs_cache.json` | Cached jobs, descriptions, emails, and AI results |
| `scan_report.json` | Per-site scan status |
| `debug/` | Debug screenshots and page snapshots |
| `profile/` | Saved browser auth sessions and cookies |

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
distance calculation, salary calculation, retries, and page guard behavior.

## Privacy And GitHub Hygiene

Do not commit `user_config.py`; it contains personal coordinates and the AI
profile. Use `user_config.example.py` as the shared template.

Do not commit generated caches, browser profiles, debug screenshots, or HTML
outputs. They can contain personal settings, cookies, contact emails, scraped
content, or transient site data.

Set `OPENAI_API_KEY` as an environment variable instead of writing it into source
files. Review `jobs_cache.json` locally before sharing any logs or artifacts,
because AI prompts and scraped descriptions may include personal or copyrighted
content from job portals.

GitHub contributors are determined from commit metadata. Keep documentation
focused on setup, usage, and project behavior rather than adding manual
contributor text.

## Legal Notes

The scraper reads public pages and does not create fake accounts. For portals
that require a user session, use the manual `--auth` flow and follow the portal's
terms. Site structure and access controls can change; check `scan_report.json`
and `debug/` when a scraper starts returning empty or blocked results.
