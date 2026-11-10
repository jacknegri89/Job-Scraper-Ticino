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

- A *Translate to Italian* button on listings written in English, German or French. It uses the browser's own translator and sends nothing; when the browser cannot translate, or the translation fails or times out, the text is left unchanged and a separate *Send the text to Google Translate* button appears. Long texts are shortened with *Show full text*.
- Exit codes a scheduler can trust: `0` success, `1` failure, `2` partial, `3` another search is running. The panel shows the same outcome.
- One search at a time per folder (a lock file, with recovery of locks left by a crash), also across the panel, the command line and scheduled tasks.
- `--ai` to ask for the AI rating on the command line, and a setting for the most listings rated per search (25 by default).
- Remote and hybrid work read from clear statements in the description, never from denials or vague mentions.
- `scrapers/pagination.py`: a shared page loop that keeps the listings already read when a later page fails and reports blocks and login walls.
- `run_scheduled.bat` for Windows Task Scheduler, using the project's `.venv`, writing `scraper.log` and passing the exit code on.
- `requirements-dev.txt`, pinned dependencies, Dependabot, a Windows test job, a dependency audit job and the security rules of bandit in the lint step.
- A CI job that installs Chromium and runs the browser tests; there a missing browser is a failure, not a skip. New browser tests for the dashboard's search, filters, sorting, themes and keyboard use.
- `tools/make_screenshots.py` redraws the pictures in `docs/` from invented listings only.

### Changed
- The dashboard is redesigned for reading: system fonts at 16 px, sentence-case labels, plain cards, one green for actions, no decoration. Descriptions are shown in paragraphs instead of one block.
- Stored descriptions can be up to 6,000 characters and are cut at a whole line.
- The project is now called JobScraper (it was Job Scraper Ticino). The old GitHub address redirects to the new one.
- The cross-border estimate treated 0.96 as EUR per CHF, about 12% below the ECB rate, and used the 2025 second IRPEF bracket and a wrong deduction formula for the 28,000-50,000 EUR band. All three are fixed.
- Italian portals are no longer rejected by the filter. Listings are placed by their location, not by a fixed list of eight municipalities (settings from earlier versions keep exactly that behaviour).
- Fields: electronics and machining are now a separate field from software, IT and AI; "Programmatore CNC" is no longer a software job.
- A listing page is opened for at most 60 new jobs per run.

- The AI is off until you switch it on (panel or `--ai`). Before, having `OPENAI_API_KEY` set could start paid requests when no settings were saved, and every cached listing was sent, including those your filters hide or that had expired.
- A source with `ok_partial` and nothing read is now a failure; a later "no results" or "partial" note can no longer hide an earlier block or failed page; listings next to a failed search are partial, not `ok`.
- A search that finished with no results now lets saved listings of that source expire; blocks, errors and partial reads still never do.
- Seniority, contract type and work mode are read again once the description is known, and unknown values are only filtered then, so an excluded "senior" listing no longer slips through and a listing is no longer dropped before its description could settle it.
- A scan where no source could be read leaves the cache and the dashboard untouched.
- The dashboard is written in one step, so a crash cannot leave a half-written page.
- The dashboard script is allowed by its hash instead of `unsafe-inline`; the panel script needs a one-time nonce.
- De-duplication compares whole company names (it truncated them to 25 characters, so two long names with the same start were merged) and keeps an AI rating that only the other copy had.
- Windows scheduling uses the project's virtual environment instead of whichever `python` is on the PATH.
- The panel and the command line refuse to start a second search while one is running.
- The backup of the previous run's cache is no longer replaced by the first save of the current run.
- The description download refused hosts outside the allowed list, but a redirect to another host was followed by the browser. Redirects are now checked before they are requested.
- The job index download is size-limited; the browser session file is readable by its owner only on Linux and macOS.
- `playwright-stealth` needs version 2 or later (the code uses its `Stealth` class); `requirements.txt` said 1.0.
- Removed four unused functions.

### Fixed
- A saved listing that the portal still showed was marked "possibly expired" when the current filters (field, seniority, contract, area) hid it, because only the wanted listings were compared with the cache. Every listing seen in a scan now counts as seen; the filters decide only what is shown, what gets a description and what the AI rates.
- With a seniority or contract filter that leaves out "Not stated", every listing whose description had not been read yet was hidden from the dashboard (on a real cache, 276 of 327). "Not stated" now hides a listing only after its text has been read, as the scan already did.
- The AI no longer rates a listing whose description is still expected on a next search; that rating would have been paid again when the text arrived.
- The search box could not find text with `&`, quotes, apostrophes or `<`, such as "AT&T" or "O'Brien": the search text was escaped twice. It is escaped once; the markup is as safe as before.
- "Sales Developer" and similar sales titles were counted as software jobs: the rule for the word "sales" held two invisible control characters instead of word boundaries, so it never matched.
- A lock older than 12 hours was taken over even while its search was still running (a computer asleep overnight was enough), so two searches could write the same files. A lock is now released only when its process is gone or the process number belongs to another program; age is no longer a reason.
- A listing whose text contained "not found" (for example "fix 404 Not Found errors") could be marked as removed when its page was re-checked. Only the wording of a removed-listing page counts now.
- An anti-bot check page with a translated title ("Ci siamo quasi…") was reported as a changed page (`selector_broken`) instead of `blocked`.
- A listing page that keeps giving no text (a login wall, a block) was opened again on every run. After three failures it is tried once a week, and pages never opened come first.
- A job found on two portals lost its link to the second one when that portal was blocked or not scanned in a run. The link is kept until that portal is read completely and no longer lists the job.
- A failed description download no longer erases a contact address found earlier.
- If the last portal closed the browser, the description pages are opened in a new one instead of all failing.
- Login walls, buttons and cookie notices (LinkedIn's sign-in form above all) were stored and shown as the listing text. The text is now read from the listing's own part of the page and cleaned; text that still carries a sign-in form is dropped and read again.
- Seniority, contract type and remote work were guessed from that page furniture (for example "Internship"); they now come from the listing text only.
- Categories: fashion and product developers, sales roles ("Venditore IA") and real-estate developers were counted as software jobs; PLC and HMI programming is now "Electronics & machining".
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
