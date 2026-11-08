# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private reporting instead: open the **Security** tab of this repository and choose **Report a vulnerability**.

Include what you found, the steps to reproduce it and the impact you expect. You can expect an answer within a few days.

## Scope

This project runs on your own computer. The parts most worth reviewing are:

- the local control panel (`setup_panel.py`), which serves a page on `127.0.0.1` and starts the scraper;
- the generated dashboard (`dashboard_builder.py`), which displays text scraped from third-party sites;
- the description download in `scrapers/__init__.py`, which is limited to a list of allowed HTTPS hosts.

## Supported versions

Only the latest release on the `main` branch receives fixes.

## What the project already does

- The panel listens on `127.0.0.1` only, behind a random secret path, and checks the `Host` and `Origin` headers, a CSRF token and a request limit.
- The dashboard sets a Content-Security-Policy that blocks external resources, and escapes all scraped text and URLs.
- API keys are read from the environment and never written to disk or shown in the panel.
