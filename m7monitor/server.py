import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import constants
from .models import BandState


class OverlayServer:
    def __init__(self, state: BandState, host: str = constants.OVERLAY_HOST, port: int = constants.OVERLAY_PORT):
        self.state = state
        self.host = host
        self.port = port
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._html_content: Optional[str] = None
        self._css_content: Optional[str] = None
        self._js_content: Optional[str] = None

    def _load_html(self) -> str:
        if self._html_content is None:
            html_path = Path(__file__).parent / "static" / "overlay.html"
            with open(html_path, "r", encoding="utf-8") as f:
                self._html_content = f.read()
        return self._html_content

    def _load_css(self) -> str:
        if self._css_content is None:
            css_path = Path(__file__).parent / "static" / "overlay.css"
            with open(css_path, "r", encoding="utf-8") as f:
                self._css_content = f.read()
        return self._css_content

    def _load_js(self) -> str:
        if self._js_content is None:
            js_path = Path(__file__).parent / "static" / "overlay.js"
            with open(js_path, "r", encoding="utf-8") as f:
                self._js_content = f.read()
        return self._js_content

    def start(self):
        state = self.state
        server_instance = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    html = server_instance._load_html()
                    self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                elif self.path.startswith("/index.css"):
                    css = server_instance._load_css()
                    self._send(200, "text/css; charset=utf-8", css.encode("utf-8"))
                elif self.path.startswith("/index.js"):
                    js = server_instance._load_js()
                    self._send(200, "text/js; charset=utf-8", js.encode("utf-8"))
                elif self.path.startswith("/api/state"):
                    body = json.dumps(state.as_dict(), ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", body)
                elif self.path.startswith("/health"):
                    self._send(200, "text/plain; charset=utf-8", b"ok")
                else:
                    self._send(404, "text/plain; charset=utf-8", b"not found")

            def log_message(self, *_):
                return

            def _send(self, status: int, content_type: str, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        print(f"[web] overlay: http://{self.host}:{self.port}/")
        print(f"[web] state:   http://{self.host}:{self.port}/api/state")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
