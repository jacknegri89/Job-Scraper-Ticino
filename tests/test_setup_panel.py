"""Local panel checks: access control, validation and saving."""

import http.client
import json
import threading

import pytest

import setup_panel
import startup_config


@pytest.fixture
def panel(tmp_path, monkeypatch):
    sources = {"jobs.ch", "indeed.ch"}
    settings = startup_config.default_settings(sorted(sources), ["operaio"])
    monkeypatch.setattr(startup_config, "SETTINGS_FILE", tmp_path / "user_settings.json")
    server = setup_panel.LocalPanelServer(settings, sources)
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
    assert b"JobScraper" in html


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
    settings.update(regions=["LOM"], radius_km=20, sources=["jobs.ch"], search_terms=["tecnico"])
    status, _ = request(panel, "POST", f"/{panel.token}/save", json.dumps(settings), headers)
    assert status == 200
    saved = startup_config.load_settings(startup_config.SETTINGS_FILE, panel.sources)
    assert saved["regions"] == ["LOM"]
    assert saved["radius_km"] == 20
    settings["regions"] = ["invalid"]
    status, _ = request(panel, "POST", f"/{panel.token}/save", json.dumps(settings), headers)
    assert status == 400
    assert startup_config.load_settings(startup_config.SETTINGS_FILE, panel.sources) == saved


def test_panel_rejects_declared_oversized_body(panel):
    # Only the header is oversized, so the client never sends a large body the server would leave unread.
    headers = {"Content-Type": "application/json", "Origin": f"http://{panel.host}",
               "X-CSRF-Token": panel.token, "Content-Length": str(setup_panel.MAX_BODY_BYTES + 1)}
    status, _ = request(panel, "POST", f"/{panel.token}/save", None, headers)
    assert status == 413


def test_panel_page_offers_regions_levels_contracts_and_freshness(panel):
    status, html = request(panel, "GET", f"/{panel.token}")
    assert status == 200
    for expected in (b"Where to look", b"Seniority", b"Contract", b"Freshness and exchange rate", b"Find coordinates"):
        assert expected in html


def test_panel_looks_up_a_place_for_the_starting_point(panel):
    status, payload = request(panel, "GET", f"/{panel.token}/place?name=Monza")
    result = json.loads(payload)
    assert status == 200
    assert result["found"] is True
    assert result["province"] == "MB"
    assert 45 < result["lat"] < 46


def test_panel_place_lookup_explains_ambiguous_and_unknown_names(panel):
    _, ambiguous = request(panel, "GET", f"/{panel.token}/place?name=Bodio")
    _, unknown = request(panel, "GET", f"/{panel.token}/place?name=Atlantis")
    assert json.loads(ambiguous)["found"] is False
    assert "province" in json.loads(ambiguous)["error"]
    assert json.loads(unknown)["found"] is False


def test_panel_place_lookup_needs_the_secret_path(panel):
    status, _ = request(panel, "GET", "/wrong-token/place?name=Monza")
    assert status == 404


def test_panel_is_rate_limited(panel):
    statuses = [request(panel, "GET", f"/{panel.token}/place?name=Monza")[0]
                for _ in range(setup_panel.MAX_REQUESTS_PER_MINUTE + 2)]
    assert statuses[-1] == 429
