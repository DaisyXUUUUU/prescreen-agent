import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _workbench import screen_one  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            code, out = screen_one(str(body.get("id", "")), str(body.get("version", "1.0.0")))
        except Exception as e:  # noqa: BLE001 - the page falls back to the saved result
            code, out = 500, {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
