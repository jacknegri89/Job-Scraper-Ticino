"""Personal data stays out of the repository, and only expected hosts are ever opened."""

import re
from pathlib import Path

import startup_config
from scrapers import _valid_description_url, check_listing

PROJECT_DIR = Path(__file__).resolve().parent.parent
CHECKED_SUFFIXES = {".py", ".md", ".html", ".bat", ".yml", ".toml", ".txt"}
SKIPPED_FOLDERS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "debug", "profile", "docs"}
API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def _project_text_files() -> list[Path]:
    files = []
    for path in PROJECT_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in CHECKED_SUFFIXES:
            continue
        if SKIPPED_FOLDERS & set(path.relative_to(PROJECT_DIR).parts):
            continue
        files.append(path)
    return files


def test_default_settings_contain_no_home_town_or_profile() -> None:
    settings = startup_config.default_settings(["jobs.ch"], ["operaio"])
    assert settings["home_city"] == ""
    assert settings["home_lat"] is None
    assert settings["home_lng"] is None
    assert settings["candidate_profile"] == ""


def test_example_config_has_no_personal_coordinates() -> None:
    example = (PROJECT_DIR / "user_config.example.py").read_text(encoding="utf-8")
    assert "HOME_LAT = None" in example
    assert "HOME_LNG = None" in example


def test_personal_files_are_ignored_by_git() -> None:
    ignored = (PROJECT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    for name in ("user_config.py", "user_settings.json", "jobs_cache.json", "fx_cache.json", "scan_report.json",
                 "jobs_cache.json.bak", "user_settings.json.v1.bak", "profile/", "debug/", "index.html"):
        assert name in ignored, name


def test_no_api_key_is_written_in_the_project() -> None:
    offenders = [str(path) for path in _project_text_files() if API_KEY_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []


def test_description_pages_are_only_opened_on_known_https_hosts() -> None:
    assert _valid_description_url("https://it.indeed.com/viewjob?jk=abcdef1234567890") is True
    assert _valid_description_url("https://it.linkedin.com/jobs/view/dev-123") is True
    assert _valid_description_url("http://it.indeed.com/viewjob?jk=1") is False
    assert _valid_description_url("https://evil.example/x") is False
    assert _valid_description_url("https://it.indeed.com.evil.example/x") is False
    assert _valid_description_url("https://user:pass@it.indeed.com/x") is False
    assert _valid_description_url("https://it.indeed.com:8443/x") is False


class _ForbiddenContext:
    """A browser context that fails the test if anything tries to open a page."""

    @property
    def browser(self):
        raise AssertionError("a page was opened for a URL that is not allowed")


def test_listing_check_never_opens_a_host_that_is_not_allowed() -> None:
    assert check_listing(_ForbiddenContext(), "https://evil.example/job/1") == "unknown"
    assert check_listing(_ForbiddenContext(), "javascript:alert(1)") == "unknown"
