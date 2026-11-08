"""Local panel to configure the scraper and start it in the background."""

import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import startup_config

PROJECT_DIR = Path(__file__).resolve().parent
PANEL_FILE = PROJECT_DIR / "setup_panel.html"
LOG_FILE = PROJECT_DIR / "scraper.log"
MAX_BODY_BYTES = 16384
MAX_REQUESTS_PER_MINUTE = 30


class LocalPanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings, cities, sources):
        super().__init__(("127.0.0.1", 0), PanelHandler)
        self.token = secrets.token_urlsafe(32)
        self.host = f"127.0.0.1:{self.server_port}"
        self.settings = settings
        self.cities = cities
        self.sources = sources
        self.process = None
        self.lock = threading.Lock()
        self.requests = deque()

    def status(self):
        with self.lock:
            if self.process is None:
                return "idle"
            result = self.process.poll()
            if result is None:
                return "running"
            return "complete" if result == 0 else "error"

    def save(self, settings):
        startup_config.validate_settings(settings, self.cities, self.sources)
        with self.lock:
            startup_config.save_settings(startup_config.SETTINGS_FILE, settings)
            self.settings = settings

    def start(self, settings):
        startup_config.validate_settings(settings, self.cities, self.sources)
        if settings["ai_enabled"] and not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("To use the AI analysis, set OPENAI_API_KEY and reopen the panel.")
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise ValueError("A search is already running.")
            startup_config.save_settings(startup_config.SETTINGS_FILE, settings)
            self.settings = settings
            command = [sys.executable, str(PROJECT_DIR / "main.py"), "--background", "--headless", "--project-dir"]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            with LOG_FILE.open("a", encoding="utf-8") as log_file:
                self.process = subprocess.Popen(
                    command, cwd=PROJECT_DIR, stdin=subprocess.DEVNULL,
                    stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags,
                )

    def allow_request(self):
        now = time.monotonic()
        with self.lock:
            while self.requests and self.requests[0] <= now - 60:
                self.requests.popleft()
            if len(self.requests) >= MAX_REQUESTS_PER_MINUTE:
                return False
            self.requests.append(now)
            return True


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        pass

    def _headers(self, status, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send_json(self, status, payload):
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _valid_host(self):
        return self.headers.get("Host") == self.server.host

    def do_GET(self):
        if not self._valid_host():
            return self.send_error(403)
        if self.path == f"/{self.server.token}/status":
            return self._send_json(200, {"status": self.server.status()})
        if self.path != f"/{self.server.token}":
            return self.send_error(404)
        self._serve_panel()

    def _serve_panel(self):
        data = {"token": self.server.token, "settings": self.server.settings,
                "cities": sorted(self.server.cities), "sources": sorted(self.server.sources)}
        encoded_data = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        html = PANEL_FILE.read_text(encoding="utf-8").replace("__PANEL_DATA__", encoded_data)
        self._headers(200, "text/html; charset=utf-8")
        self.wfile.write(html.encode("utf-8"))

    def _read_body(self):
        """Read the whole request body (bounded) so rejected requests never leave unread data on the socket."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.close_connection = True
            self.send_error(400)
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            self.send_error(413)
            return None
        return self.rfile.read(length)

    def _has_valid_token(self):
        provided_token = self.headers.get("X-CSRF-Token", "")
        try:
            return hmac.compare_digest(provided_token.encode("ascii"), self.server.token.encode("ascii"))
        except UnicodeEncodeError:
            return False

    def do_POST(self):
        body = self._read_body()
        if body is None:
            return
        if not self._valid_host() or self.headers.get("Origin") != f"http://{self.server.host}":
            return self.send_error(403)
        if not self._has_valid_token():
            return self.send_error(403)
        if not self.server.allow_request():
            return self._send_json(429, {"error": "Too many requests. Try again shortly."})
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self.send_error(415)
        if self.path == f"/{self.server.token}/close":
            if body != b"{}":
                return self.send_error(400)
            self._send_json(200, {"status": "closed"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path not in (f"/{self.server.token}/save", f"/{self.server.token}/start"):
            return self.send_error(404)
        self._handle_settings(body)

    def _handle_settings(self, body):
        try:
            if not body:
                return self.send_error(400)
            settings = json.loads(body.decode("utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("Invalid configuration.")
            settings["headless"] = True
            if self.path.endswith("/start"):
                self.server.start(settings)
            else:
                self.server.save(settings)
            return self._send_json(200, {"status": self.server.status()})
        except (ValueError, UnicodeError, json.JSONDecodeError) as error:
            return self._send_json(400, {"error": str(error)})
        except OSError:
            return self._send_json(500, {"error": "The operation failed. Check the folder permissions."})


def open_panel(settings, cities, sources):
    server = LocalPanelServer(settings, cities, sources)
    url = f"http://{server.host}/{server.token}"
    if sys.stdout is not None:
        print("Panel ready in your browser. Use 'Close panel' to stop it.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
