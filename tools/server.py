#!/usr/bin/env python3
"""
TigerTag playground dev server.

Serves static files from the project root AND handles:
  POST /api/diff   — runs TigerTag.diff_api() server-side via the Python SDK

Usage:
  python3 tools/server.py [port]   (default port: 7432)
"""

import json
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tigertag import TigerTag  # noqa: E402


class PlaygroundHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/diff":
            self._handle_diff()
        else:
            self.send_error(404)

    def _handle_diff(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body: dict = json.loads(self.rfile.read(length))

            uid_hex     = (body.get("uid") or "").strip()
            payload_hex = (body.get("payload") or "").strip()

            uid     = bytes.fromhex(uid_hex)     if uid_hex     else None
            payload = bytes.fromhex(payload_hex) if payload_hex else None

            if payload is None:
                raise ValueError("'payload' field is required")

            tag = TigerTag.from_pages(payload, uid=uid)

            api_data  = None
            api_error = None
            try:
                api_data = tag.raw_api()
            except Exception as exc:
                api_error = str(exc)

            diffs = []
            if api_data:
                for d in tag.diff_api(api_data=api_data):
                    diffs.append({
                        "field":      d.field,
                        "chip_value": d.chip_value,
                        "api_value":  d.api_value,
                    })

            result = {
                "api_data": api_data,
                "diffs":    diffs,
                "in_sync":  api_data is not None and len(diffs) == 0,
                "error":    api_error,
            }
            self._json(200, result)

        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args) -> None:  # silence request log
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7432
    httpd = HTTPServer(("", port), PlaygroundHandler)
    print(f"TigerTag playground → http://localhost:{port}/tools/playground.html")
    httpd.serve_forever()
