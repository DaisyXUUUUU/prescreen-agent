import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _workbench import state  # noqa: E402

from src import config  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        st = state()
        body = json.dumps({"live": st["model"] is not None, "checked": True, "model": config.BEDROCK_MODEL_ID,
                           "reason": None if st["model"] else st["error"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
