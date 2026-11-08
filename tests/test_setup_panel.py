"""Local panel checks: access control, validation and saving."""

import http.client
import json
import threading

import pytest

import setup_panel
import startup_config


@pytest.fixture
def panel(tmp_path, monkeypatch):
    cities = {"chiasso", "mendrisio"}
    sources = {"jobs.ch", "indeed.ch"}
    settings = startup_config.default_settings(cities, sorted(sources), ["operaio"])
    monkeypatch.setattr(startup_config, "SETTINGS_FILE", tmp_path / "user_settings.json")
    server = setup_panel.LocalPanelServer(settings, cities, sources)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def request(panel, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", panel.server_port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def test_panel_requires_unpredictable_path(panel):
    status, _ = request(panel, "GET", "/")
    assert status == 404
    status, html = request(panel, "GET", f"/{panel.token}")
    assert status == 200
    assert b"Job Scraper Ticino" in html


def test_panel_rejects_cross_origin_and_missing_token(panel):
    headers = {"Content-Type": "application/json", "Origin": "http://attacker.example"}
    status, _ = request(panel, "POST", f"/{panel.token}/save", "{}", headers)
    assert status == 403
    headers["Origin"] = f"http://{panel.host}"
    status, _ = request(panel, "POST", f"/{panel.token}/save", "{}", headers)
    assert status == 403


def test_panel_saves_valid_choices_and_rejects_invalid_ones(panel):
    headers = {"Content-Type": "application/json", "Origin": f"http://{panel.host}",
               "X-CSRF-Token": panel.token}
    settings = dict(panel.settings)
    settings.update(cities=["chiasso"], sources=["jobs.ch"], search_terms=["tecnico"])
    status, _ = request(panel, "POST", f"/{panel.token}/save", json.dumps(settings), headers)
    assert status == 200
    saved = startup_config.load_settings(startup_config.SETTINGS_FILE, panel.cities, panel.sources)
    assert saved["cities"] == ["chiasso"]
    settings["cities"] = ["invalid"]
    status, _ = request(panel, "POST", f"/{panel.token}/save", json.dumps(settings), headers)
    assert status == 400
    assert startup_config.load_settings(startup_config.SETTINGS_FILE, panel.cities, panel.sources) == saved


def test_panel_rejects_declared_oversized_body(panel):
    # Only the header is oversized, so the client never sends a large body the server would leave unread.
    headers = {"Content-Type": "application/json", "Origin": f"http://{panel.host}",
               "X-CSRF-Token": panel.token, "Content-Length": str(setup_panel.MAX_BODY_BYTES + 1)}
    status, _ = request(panel, "POST", f"/{panel.token}/save", None, headers)
    assert status == 413
