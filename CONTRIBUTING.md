# Contributing

Thanks for taking the time to improve Job Scraper Ticino. Bug reports, fixes for broken scrapers and new sources are all welcome.

## Set up

```bash
git clone https://github.com/jacknegri89/Job-Scraper-Ticino.git
cd Job-Scraper-Ticino
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt ruff
python -m playwright install chromium
```

Run the checks before you open a pull request:

```bash
python -m pytest -q
python -m ruff check .
```

The tests never contact a portal. To check the live portals, run `python main.py --dry-run`.

## A scraper stopped working

Portals change their pages, so this is the most common kind of fix.

1. Run `python main.py --dry-run --only <source>` and read `scan_report.json`. The `status` and `reason` fields tell you whether the portal is blocking you, asking for a login, or has changed its selectors.
2. Screenshots of failures are written to `debug/` (not committed).
3. Fix the selectors in `scrapers/<source>_ch.py` and, if the entry page changed, the probe in the `PROBES` table of `main.py`.
4. Add a test for any logic you changed, such as pagination or parsing, using fake pages as in `tests/test_jobs_ch.py`.

## Adding a source

1. Create `scrapers/<name>_ch.py` with a `scrape_<name>_ch(context)` function decorated with `@retry()` that returns a list of dictionaries with `title`, `company`, `city`, `date`, `url`, `category` and `source`.
2. Register it in the `SCRAPERS` list of `main.py`, add a probe to `PROBES`, and add a label to `SOURCE_LABEL` in `dashboard_builder.py`.
3. Use a fresh page per search term and always close pages in a `finally` block.
4. Run `python main.py --dry-run --only <name>` and `python main.py --scan-only --only <name>` and include the result in your pull request.

## Guidelines

- Keep changes small and focused. Do not reformat files you are not changing.
- Prefer clear, step-by-step code over clever one-liners, and give variables descriptive names.
- Anything that comes from the network is untrusted: validate it, and escape it before it reaches HTML.
- Never commit personal data: `user_config.py`, `user_settings.json`, caches, sessions, screenshots from `debug/` or generated dashboards.
- Respect each portal's terms of use. Do not add code that bypasses logins, CAPTCHAs or rate limits.
- Add or update tests for behaviour you change, and update the README when you change how the project is used.

## Pull requests

Describe what changed and why, and say how you checked it. A pull request that passes the tests and the linter and explains its reasoning is easy to review.
