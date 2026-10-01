"""Dashboard + JSON API. Binds to 127.0.0.1 unless told otherwise."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import actions

PAGE = os.path.join(os.path.dirname(__file__), "web", "index.html")


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                with open(PAGE, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if self.path.startswith("/api/state"):
                return self._json(actions.snapshot(store))
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            parts = self.path.strip("/").split("/")
            if self.path == "/api/revoke":
                return self._json(actions.revoke(store, body["id"], body.get("by", "jane")))
            if self.path == "/api/restore":
                return self._json(actions.restore(store, body["id"], body.get("by", "jane")))
            if len(parts) == 4 and parts[:2] == ["api", "holds"] and parts[3] in ("approve", "decline"):
                fn = actions.approve_hold if parts[3] == "approve" else actions.decline_hold
                return self._json(fn(store, parts[2], body.get("by", "tom")))
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(store, host="127.0.0.1", port=8765):
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
