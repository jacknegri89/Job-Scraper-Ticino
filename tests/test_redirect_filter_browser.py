"""The description request filter in a real Chromium, against local servers.

This proves that a redirect to another host is never requested. It needs the Playwright
browser (python -m playwright install chromium) and is skipped when it is not installed.
"""

import http.server
import threading

import pytest

import scrapers

sync_api = pytest.importorskip("playwright.sync_api")


class _Server:
    def __init__(self, handler_class) -> None:
        self.http_server = http.server.HTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.http_server.server_port
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.http_server.shutdown()
        self.http_server.server_close()


@pytest.fixture
def servers():
    hits = {"other_host": 0, "page": 0}

    class OtherHost(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits["other_host"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"must never be requested")

        def log_message(self, *_args):
            pass

    other_host = _Server(OtherHost)

    class Portal(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/page":
                hits["page"] += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>the real listing</body></html>")
                return
            location = f"http://127.0.0.1:{other_host.port}/secret" if self.path == "/evil" else "/page"
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, *_args):
            pass

    portal = _Server(Portal)
    yield portal, hits
    portal.stop()
    other_host.stop()


@pytest.fixture(scope="module")
def browser():
    """One Chromium for the whole module; the tests are skipped when it is not installed."""
    with sync_api.sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f"Chromium is not available: {type(error).__name__}")
        yield chromium
        chromium.close()


def _open(browser, portal_port: int, path: str, monkeypatch) -> str:
    portal_prefix = f"http://127.0.0.1:{portal_port}/"
    monkeypatch.setattr(scrapers, "_valid_description_url", lambda url: url.startswith(portal_prefix))
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.route("**/*", scrapers._filter_description_request)
        try:
            page.goto(portal_prefix + path, timeout=5000)
            return page.inner_text("body")
        except Exception:
            return "BLOCKED"
    finally:
        context.close()


def test_a_redirect_to_another_host_is_never_requested(browser, servers, monkeypatch) -> None:
    portal, hits = servers

    outcome = _open(browser, portal.port, "evil", monkeypatch)

    assert outcome == "BLOCKED"
    assert hits["other_host"] == 0


def test_a_redirect_inside_the_allowed_portal_still_works(browser, servers, monkeypatch) -> None:
    portal, hits = servers

    outcome = _open(browser, portal.port, "good", monkeypatch)

    assert outcome == "the real listing"
    assert hits["other_host"] == 0
