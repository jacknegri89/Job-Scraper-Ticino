"""The browser tests may be skipped on a laptop, never in the CI job that exists to run them."""

import pytest

import conftest


def test_a_missing_browser_is_only_a_skip_on_a_developer_machine(monkeypatch) -> None:
    monkeypatch.delenv(conftest.REQUIRE_BROWSER_VARIABLE, raising=False)

    with pytest.raises(pytest.skip.Exception):
        conftest.report_missing_browser(RuntimeError("no browser"))


def test_a_missing_browser_is_a_failure_where_the_browser_is_required(monkeypatch) -> None:
    monkeypatch.setenv(conftest.REQUIRE_BROWSER_VARIABLE, "1")

    with pytest.raises(pytest.fail.Exception):
        conftest.report_missing_browser(RuntimeError("no browser"))


def test_the_ci_has_a_job_that_requires_the_browser() -> None:
    workflow = (conftest.PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert f'{conftest.REQUIRE_BROWSER_VARIABLE}: "1"' in workflow
    assert "playwright install --with-deps chromium" in workflow


def test_every_browser_test_file_runs_in_that_job() -> None:
    """A new browser test file must be added to the job, or it would only run where it may be skipped."""
    workflow = (conftest.PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    tests_folder = conftest.PROJECT_ROOT / "tests"
    browser_test_files = [path.name for path in sorted(tests_folder.glob("test_*.py"))
                          if "(browser" in path.read_text(encoding="utf-8")]

    assert browser_test_files, "the browser tests were not found"
    for file_name in browser_test_files:
        assert f"tests/{file_name}" in workflow, f"{file_name} is missing from the browser job"
