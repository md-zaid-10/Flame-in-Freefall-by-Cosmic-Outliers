"""Serve the frontend and answer live questions. Standard library only.

    venv/bin/python frontend/serve.py          # http://localhost:8765

The demo questions come from data/demo.js and need no server; opening
index.html directly works for those. This server adds /api/ask for any other
question, calling rag.ask() from rag/search.py.

Hosted on Render (see deploy/README.md) it also serves the API to the GitHub
Pages copy of the site, so HOST, CORS and a per-visitor limit are configurable:
    HOST              default 127.0.0.1; 0.0.0.0 inside a container
    PORT              default 8765
    FIF_CORS_ORIGIN   default *; e.g. https://md-zaid-10.github.io
    FIF_RATE_LIMIT    new (uncached) questions per visitor per 10 minutes, default 20
"""
import functools
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]

from rag import search as rag  # noqa: E402
from shape import shape  # noqa: E402

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
CORS_ORIGIN = os.environ.get("FIF_CORS_ORIGIN", "*")
RATE_LIMIT = int(os.environ.get("FIF_RATE_LIMIT", "20"))
RATE_WINDOW = 600  # seconds
_lock = threading.Lock()  # the retriever is not documented as thread-safe
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def allow(ip: str) -> bool:
    """Sliding-window limit on new questions per visitor, to protect the LLM quota."""
    now = time.time()
    with _hits_lock:
        recent = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW]
        if len(recent) >= RATE_LIMIT:
            _hits[ip] = recent
            return False
        _hits[ip] = recent + [now]
        if len(_hits) > 5000:  # forget idle visitors
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                del _hits[k]
        return True


_cached_questions: set[str] = set()  # questions already answered (not rate limited)


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
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Cache-Control", "no-store")
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
            if q not in _cached_questions and not allow(self._client_ip()):
                return self._json(json.dumps({"error": "Too many new questions from your connection. "
                                              "Please wait a few minutes and try again."}), 429)
            try:
                body = ask(q)
                if len(_cached_questions) < 5000:
                    _cached_questions.add(q)
                return self._json(body)
            except Exception as e:  # surface the failure instead of hanging the UI
                return self._json(json.dumps({"error": f"{type(e).__name__}: {e}"}), 500)
        return super().do_GET()

    def _client_ip(self) -> str:
        # Behind a hosting proxy the visitor's address is the first X-Forwarded-For entry.
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    if not rag.available():
        sys.exit("RAG corpus not built (data/rag/chunks.jsonl missing).")
    # Load the search index in the background so the first visitor does not wait for it.
    threading.Thread(target=lambda: (rag._get_ledger(), print("Search index loaded.", flush=True)),
                     daemon=True).start()
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0") else HOST
    print(f"FlameScope frontend: http://{shown}:{PORT}", flush=True)
    http.server.ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
