"""Serve the frontend and answer live questions. Standard library only.

    venv/bin/python frontend/serve.py          # http://localhost:8765

The demo questions come from data/demo.js and need no server; opening
index.html directly works for those. This server adds /api/ask for any other
question, calling rag.ask() exactly as app.py does.
"""
import functools
import http.server
import json
import os
import sys
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]

from rag import search as rag  # noqa: E402
from shape import shape  # noqa: E402

PORT = int(os.environ.get("PORT", "8765"))
_lock = threading.Lock()  # the retriever is not documented as thread-safe


@functools.lru_cache(maxsize=256)
def ask(q: str) -> str:
    with _lock:
        return json.dumps(shape(rag.ask(q)), ensure_ascii=False)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def _json(self, body: str, status: int = 200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/health":
            return self._json(json.dumps({"live": rag.available()}))
        if url.path == "/api/ask":
            q = " ".join(urllib.parse.parse_qs(url.query).get("q", [""])[0].split())[:300]
            if not q:
                return self._json(json.dumps({"error": "empty question"}), 400)
            try:
                return self._json(ask(q))
            except Exception as e:  # surface the failure instead of hanging the UI
                return self._json(json.dumps({"error": f"{type(e).__name__}: {e}"}), 500)
        return super().do_GET()

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    if not rag.available():
        sys.exit("RAG corpus not built (data/rag/chunks.jsonl missing).")
    print(f"FlameScope frontend: http://localhost:{PORT}  (first live question loads the index)")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
