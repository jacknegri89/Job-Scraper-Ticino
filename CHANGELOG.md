# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- The project is now called JobScraper (it was Job Scraper Ticino). The old GitHub address redirects to the new one.

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
