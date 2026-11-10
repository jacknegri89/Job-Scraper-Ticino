"""Shared test setup: one real Chromium for the tests that need a browser.

On a developer machine without the Playwright browser those tests are skipped. In the CI job
that exists to run them, JOBSCRAPER_REQUIRE_BROWSER=1 turns a missing browser into a failure,
so they can never disappear from the results without anyone noticing.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REQUIRE_BROWSER_VARIABLE = "JOBSCRAPER_REQUIRE_BROWSER"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def browser_is_required() -> bool:
    return os.environ.get(REQUIRE_BROWSER_VARIABLE, "") == "1"


def report_missing_browser(error: Exception) -> None:
    """Fail where the browser is required, skip everywhere else."""
    message = f"Chromium could not start ({type(error).__name__}). Install it with: python -m playwright install chromium"
    if browser_is_required():
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def browser():
    """One headless Chromium for the whole test run."""
    with sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch(headless=True)
        except Exception as error:
            report_missing_browser(error)
        yield chromium
        chromium.close()
