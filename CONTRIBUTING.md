# Contributing

Thanks for taking the time to improve JobScraper. Bug reports, fixes for broken scrapers and new sources are all welcome.

## Set up

```bash
git clone https://github.com/jacknegri89/JobScraper.git
cd JobScraper
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt   # runtime dependencies plus pytest and ruff
python -m playwright install chromium
```

Run the checks before you open a pull request:

```bash
python -m pytest -q
python -m ruff check .
```

The tests never contact a portal. Two of them start a local server and a real Chromium to prove that redirects to other hosts are refused; they are skipped when Chromium is not installed. To check the live portals, run `python main.py --dry-run --only .`.

## A scraper stopped working

Portals change their pages, so this is the most common kind of fix.

1. Run `python main.py --dry-run --only <source>` and read `scan_report.json`. The `status` and `reason` fields tell you whether the portal is blocking you, asking for a login, or has changed its selectors.
2. Screenshots of failures are written to `debug/` (not committed).
3. Fix the selectors in `scrapers/<source>.py` (for example `scrapers/indeed_ch.py` or `scrapers/italy_portals.py`) and, if the entry page changed, the probe in the `PROBES` table of `dry_run.py`.
4. Add a test for any logic you changed, such as pagination or parsing, using fake pages as in `tests/test_jobs_ch.py`.

## Adding a source

1. Create `scrapers/<name>.py` with a `scrape_<name>(context)` function decorated with `@retry()` that returns a list of dictionaries with `title`, `company`, `city`, `date`, `url`, `category` and `source`. Name the source after its domain: a name ending in `.ch` is read as Swiss and one ending in `.it` as Italian. If the portal shows a salary line on its cards, return it as `salary_text`; never guess one.
   Report an honest status: `ok` when listings were read, `no_results` only when the page itself says nothing matches, `selector_broken` when the page loaded but no cards were found, and `blocked` or `requires_auth` when a captcha or a login appears (stop there, never bypass it). Call `run_report.set_status(...)` for a problem on one page; a source with nothing read is a failure whatever the note says, and a weaker note never replaces a stronger one. Only report `ok` when every search ran to the end: a source whose searches partly failed is `ok_partial`.
2. For portals that list jobs over several pages, use `collect_pages` from `scrapers/pagination.py`: a page that fails after some listings were read ends the loop as a partial read, and an empty page is checked for a block or login wall, which stops the portal for this scan.
3. Register the source in the `SCRAPERS` list of `main.py`, add a probe to `PROBES` in `dry_run.py`, and add a label to `SOURCE_LABEL` in `dashboard_builder.py`.
4. Use a fresh page per search term and always close pages in a `finally` block.
5. Add the portal's host to `DESCRIPTION_HOSTS` in `scrapers/__init__.py` if its description pages may be opened. Run `python main.py --dry-run --only <name>` and `python main.py --scan-only --only <name>` and include the result in your pull request. Do not put real portal pages in the tests: use simulated pages, as in `tests/test_pagination.py`.

## Guidelines

- Keep changes small and focused. Do not reformat files you are not changing.
- Prefer clear, step-by-step code over clever one-liners, and give variables descriptive names.
- Anything that comes from the network is untrusted: validate it, and escape it before it reaches HTML.
- Never commit personal data: `user_config.py`, `user_settings.json`, caches, sessions, screenshots from `debug/` or generated dashboards.
- Respect each portal's terms of use. Do not add code that bypasses logins, CAPTCHAs or rate limits.
- Add or update tests for behaviour you change, and update the README when you change how the project is used.

## Pull requests

Describe what changed and why, and say how you checked it. A pull request that passes the tests and the linter and explains its reasoning is easy to review.
