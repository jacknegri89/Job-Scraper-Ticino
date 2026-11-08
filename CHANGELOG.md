# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
