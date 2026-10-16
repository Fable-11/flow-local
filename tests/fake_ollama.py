"""Tiny local HTTP server imitating the Ollama endpoints we use."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeServer:
    """Tiny local HTTP server imitating the Ollama endpoints we use."""

    def __init__(self, reply="Hello world.", delay=0.0, models=("qwen2.5:7b-instruct",)):
        outer = self
        self.reply, self.delay, self.models = reply, delay, list(models)
        self.last_payload = None

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send({"version": "x"})
                else:
                    self._send({"models": [{"name": m} for m in outer.models]})

            def do_POST(self):
                n = int(self.headers["Content-Length"])
                outer.last_payload = json.loads(self.rfile.read(n))
                time.sleep(outer.delay)
                self._send({"message": {"role": "assistant", "content": outer.reply}})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
