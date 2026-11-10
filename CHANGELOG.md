# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.2.0] - 2026-11-10

### Added
- **Readable listing text.** Only the text of the listing is stored (login walls, buttons and cookie notices are removed) and shown in paragraphs, up to 6,000 characters, with *Show full text*.
- **Translate to Italian** for listings in English, German or French, done by the browser's own translator on the device. If the browser cannot translate, the text stays unchanged and a separate *Send the text to Google Translate* button appears.
- **Exit codes** a scheduler can trust (`0` success, `1` failure, `2` partial, `3` another search is running) and **one search at a time per folder**, across the panel, the command line and scheduled tasks.
- `--ai` on the command line and a cap on the listings rated per search (25 by default).
- Remote and hybrid work read from clear statements in the description, never from denials or vague mentions.
- `run_scheduled.bat` for Windows Task Scheduler, using the project's `.venv` and passing the exit code on.
- Pinned dependencies, `requirements-dev.txt`, Dependabot, and CI jobs for Windows, for the dependency audit and for the browser tests (there a missing Chromium is a failure, not a skip).
- `tools/make_screenshots.py` redraws the pictures in `docs/` from invented listings only.

### Changed
- **The dashboard is redesigned for reading**: system fonts at 16 px, plain cards, one colour for actions. A listing whose text could not be read says so.
- **The AI is off until you switch it on** (panel or `--ai`); `OPENAI_API_KEY` alone starts nothing. It rates only visible, non-expired listings that have a description: never from the title alone, so never twice.
- **Seen is not the same as wanted.** Every listing a scan finds counts as seen; the filters decide only what is shown, what gets a description and what the AI rates. "Not stated" seniority or contract hides a listing only after its text has been read.
- Scan outcomes are stricter: a source with nothing read is a failure, a block is never hidden by a later note, a search with no results lets saved listings expire, and a scan where no source could be read leaves the cache and the dashboard untouched.
- A listing page that keeps giving no text is tried three times, then once a week.
- Fields: fashion and product developers, sales and real-estate roles are no longer software jobs; PLC and HMI programming is "Electronics & machining"; a customer-service "help desk" is IT only when its description says so.
- De-duplication compares whole company names and keeps the link to a portal that was blocked in a run.

### Fixed
- A saved listing that was still online was marked "possibly expired" when a filter hid it.
- Login walls and cookie notices were stored and shown as listing text, and seniority or contract were guessed from them.
- The search box could not find text with `&`, quotes or apostrophes (the text was escaped twice).
- A lock older than 12 hours was taken from a search that was still running, and two searches could both take a lock left by a crash.
- A listing whose text said "not found" could be marked as removed; a translated anti-bot page was reported as a changed page instead of a block.
- A control character in the "sales" rule kept it from ever matching, so sales titles counted as software jobs.
- The backup of the previous run's cache was replaced by the first save of the current run.

### Security
- Description pages: a redirect to a host outside the allowed list is refused before it is requested.
- The dashboard script is allowed by its hash and the panel script by a one-time nonce, instead of `unsafe-inline`; the dashboard is written in one step.
- Downloads are size-limited, and the browser session file is readable by its owner only on Linux and macOS.

## [1.1.0] - 2026-11-08

### Added
- Lombardy next to Ticino: Indeed Italia and LinkedIn Italia, about 2,500 places known offline, a search area made of regions, a radius around your starting point and extra towns or provinces.
- A common job shape for every portal (country, region, place and its certainty, seniority, contract, remote or hybrid, canonical link and every portal link).
- Freshness: first seen, last seen, last verified and a status (seen in the latest scan, not re-checked, possibly expired, page checked, gone). Blocked portals never delete cached jobs.
- Seniority and contract filters that keep "Senior" listings unless the user switches them off; imprecise and remote locations are separate options.
- Salary reading from listings (currency, period, ranges, gross or net, 13th and 14th month, employment percentage, "up to" and "from" limits) and a resolver that always prefers a written salary to an AI estimate.
- Italian net pay estimate (tax year 2026) and an exchange rate with a visible source and date (ECB daily rate or a manual one).
- AI cache keys covering prompt version, model, candidate profile and listing text; stale, unanalyzable and pending states; strict validation of AI answers.
- Scan report with listings read, valid, duplicates and exclusion reasons per source, and an explicit overall `success`, `partial` or `failure`.
- Settings version 2 with an automatic migration and a one-time `.v1.bak` backup; atomic cache writes with backups.
- The panel can look a town up for the starting point and choose every new option.

### Changed
- The project is now called JobScraper (it was Job Scraper Ticino). The old GitHub address redirects to the new one.
- The cross-border estimate treated 0.96 as EUR per CHF, about 12% below the ECB rate, and used the 2025 second IRPEF bracket and a wrong deduction formula for the 28,000-50,000 EUR band. All three are fixed.
- Italian portals are no longer rejected by the filter. Listings are placed by their location, not by a fixed list of eight municipalities (settings from earlier versions keep exactly that behaviour).
- Fields: electronics and machining are now a separate field from software, IT and AI; "Programmatore CNC" is no longer a software job.
- A listing page is opened for at most 60 new jobs per run.

### Fixed
- AI results were reused after the candidate profile changed.
- A page that was an anti-bot message could be stored as a job description.
- A salary written as "28.000 € - 32.000 € all'anno" was read as a single amount.

## [1.0.0] - 2026-11-08

First public release.

### Added
- Scrapers for eleven Swiss job portals, filtered to eight municipalities around Chiasso and Mendrisio, with de-duplication across portals.
- Dashboard with search, sorting, category filters, distance ruler and estimated net salary in Italy, in light and dark themes, loading no external resources.
- Local control panel to choose municipalities, sources and search terms, with a background search.
- Optional AI rating of listings against a personal profile.
- Cache, partial-scan protection and `scan_report.json` for failed or empty sources.
- Dry-run mode that checks every portal in minutes.
- Windows launcher and scheduled daily search.
- GitHub Actions workflow running the linter and the tests on Python 3.10 and 3.12.

### Fixed
- jobs.ch: a crashed page no longer ruins the remaining search terms, and pagination stops when the portal repeats results.
- Panel: rejected requests no longer cause a connection reset on Windows.
- Distances are hidden when no starting point is configured, instead of being computed from placeholder coordinates.

[1.2.0]: https://github.com/jacknegri89/JobScraper/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jacknegri89/JobScraper/releases/tag/v1.1.0
