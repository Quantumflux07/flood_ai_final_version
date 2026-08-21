"""dashboard_server.py -- Python HTTP backend & REST API server for FlowShield.

Serves V2 REST API endpoints and dashboard static assets with ThreadingHTTPServer.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Add src parent directory to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api.handlers import FlowShieldAPIHandler
from src.engine.state_manager import FlowShieldV2Manager

# Static assets directory
STATIC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "src", "dashboard")
)

# Global state manager and API handler instances
manager = FlowShieldV2Manager()
api_handler = FlowShieldAPIHandler(manager=manager)


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress log spam in test/dev server
        pass

    def end_headers(self):
        # CORS Headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status_code: int, data: dict):
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_body(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return {}
            body = self.rfile.read(content_length).decode("utf-8")
            return json.loads(body)
        except Exception:
            return {}

    def do_GET(self):
        try:
            parsed_url = urllib.parse.urlparse(self.path)
            path = parsed_url.path

            # ── V2 REST API Endpoints ──────────────────────────────────────────
            if path == "/api/state":
                code, data = api_handler.handle_get_state()
                self._send_json(code, data)
                return

            if path == "/api/incidents":
                code, data = api_handler.handle_get_incidents()
                self._send_json(code, data)
                return

            if path == "/api/resources":
                code, data = api_handler.handle_get_resources()
                self._send_json(code, data)
                return

            if path == "/api/decisions":
                code, data = api_handler.handle_get_decisions()
                self._send_json(code, data)
                return

            if path == "/api/allocations":
                code, data = api_handler.handle_get_allocations()
                self._send_json(code, data)
                return

            # ── Static dashboard files ─────────────────────────────────────────
            if path == "/":
                file_path = os.path.join(STATIC_DIR, "index.html")
                content_type = "text/html"
            else:
                rel_file = path.lstrip("/")
                file_path = os.path.join(STATIC_DIR, rel_file)
                if file_path.endswith(".css"):
                    content_type = "text/css"
                elif file_path.endswith(".js"):
                    content_type = "application/javascript"
                elif file_path.endswith(".png"):
                    content_type = "image/png"
                elif file_path.endswith(".svg"):
                    content_type = "image/svg+xml"
                else:
                    content_type = "text/plain"

            file_path = os.path.normpath(file_path)
            if not file_path.startswith(STATIC_DIR):
                self.send_error(403, "Access Denied")
                return

            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, f"File Not Found: {path}")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            parsed_url = urllib.parse.urlparse(self.path)
            path = parsed_url.path
            body = self._read_json_body()

            # ── V2 REST API Endpoints ──────────────────────────────────────────
            if path == "/api/input/analyze":
                code, data = api_handler.handle_analyze_input(body)
                self._send_json(code, data)
                return

            if path == "/api/input/execute":
                code, data = api_handler.handle_execute_input(body)
                self._send_json(code, data)
                return

            if path == "/api/state/update":
                code, data = api_handler.handle_state_update(body)
                self._send_json(code, data)
                return

            if path == "/api/simulation":
                code, data = api_handler.handle_simulation(body)
                self._send_json(code, data)
                return

            if path == "/api/reset":
                code, data = api_handler.handle_reset()
                self._send_json(code, data)
                return

            # ── Legacy Ingest Endpoint (Backwards compatibility) ────────────────
            if path == "/api/ingest":
                report_text = body.get("report_text")
                zone_id_hint = body.get("zone_id_hint")
                if not report_text or not str(report_text).strip():
                    self._send_json(
                        200, {"success": False, "errors": ["Report text is required."]}
                    )
                    return

                res = manager.execute_input(report_text, zone_id_hint)
                if res.get("status") in ("clarify", "rejected", "error"):
                    err_msg = (
                        res.get("reason")
                        or res.get("message")
                        or "Input not accepted."
                    )
                    self._send_json(200, {
                        "success": False,
                        "errors": [err_msg],
                        "warnings": res.get("missing_information", []),
                    })
                else:
                    inc = res.get("incident", {})
                    self._send_json(200, {
                        "success": True,
                        "incident_id": inc.get("id"),
                        "title": inc.get("title"),
                        "severity": inc.get("severity"),
                        "zone_id": inc.get("zone_id"),
                    })
                return

            self.send_error(404, "Endpoint Not Found")
        except (BrokenPipeError, ConnectionResetError):
            pass


def run(port=8000):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, DashboardHTTPHandler)
    print(f"FlowShield Dashboard Server started at http://localhost:{port}/")
    print(f"Serving static assets from: {STATIC_DIR}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    port_val = 8000
    if len(sys.argv) > 1:
        try:
            port_val = int(sys.argv[1])
        except ValueError:
            pass
    run(port=port_val)
