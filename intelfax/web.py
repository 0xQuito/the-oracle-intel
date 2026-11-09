"""Browser version: a small local web server that renders the same pages
as the terminal app and sends them to web/index.html as coloured text runs.

Browsers can't fetch most of these feeds directly (cross-origin rules), so
the fetching stays here in Python and the page just draws what it's given."""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import nav, pages
from .app import Context, body_rows, fastext_row, paginate, status_row
from .feeds import FeedManager

FEEDS = FeedManager()
CLIENT = Path(__file__).parent / "web" / "index.html"
CONFIG = {"cols": 80, "rows": 32}


def _hex(c):
    return "#%02x%02x%02x" % c


def runs(row, width):
    """Row -> [[text, fg, bg], ...] with neighbouring same-colour cells merged."""
    out = []
    for ch, fg, bg in row.cells(width):
        if out and out[-1][1] == fg and out[-1][2] == bg:
            out[-1][0] += ch
        else:
            out.append([ch, fg, bg])
    return [[t, _hex(f), _hex(b)] for t, f, b in out]


def _int(q, key, default, lo, hi):
    try:
        return max(lo, min(hi, int(q.get(key, [default])[0])))
    except ValueError:
        return default


def page_json(q):
    n = _int(q, "n", 100, 100, 899)
    W = _int(q, "cols", CONFIG["cols"], 40, 160)
    H = _int(q, "rows", CONFIG["rows"], 25, 60) - 8  # header, banner x3, title, status, links, prompt
    fresh = q.get("fresh", ["0"])[0] == "1"
    r = pages.resolve(n)
    if r:
        for f in r[0]:
            FEEDS.request(f)
        busy = [f for f in r[0] if FEEDS.pending(f) or (fresh and FEEDS.states[f].loading)]
        if busy:
            return {"ready": False}
    ctx = Context(W, FEEDS, H)
    ctx.reveal = q.get("reveal", ["0"])[0] == "1"
    spec = (r[1](ctx) if r else None) or pages.not_found(n)
    subs = paginate(spec.blocks, H, spec.max_subpages)
    sub = _int(q, "sub", 0, -999, 999) % len(subs)
    rows = body_rows(spec, subs, sub, W, H) + [status_row(spec), fastext_row(spec, W)]
    link = spec.link if spec.link.startswith(("https://", "http://")) else ""
    items = [{**it, "hl": _hex(it["hl"])} for it in nav.selectables(spec, subs, sub, W, H)]
    return {"ready": True, "found": r is not None, "n": n, "sub": sub, "subs": len(subs),
            "rows": [runs(row, W) for row in rows], "fills": [_hex(row.fill) for row in rows],
            "items": items, "fastext": [p for _, p in spec.fastext[:4]],
            "link": link, "version": FEEDS.version}


def step_json(q):
    n = _int(q, "n", 100, 100, 899)
    d = 1 if _int(q, "d", 1, -1, 1) >= 0 else -1
    ctx = Context(CONFIG["cols"], FEEDS)
    for _ in range(800):
        n = (n - 100 + d) % 800 + 100
        if pages.exists(n, ctx):
            break
    return {"n": n}


def refresh_json(q):
    r = pages.resolve(_int(q, "n", 100, 100, 899))
    for f in (r[0] if r else []):
        FEEDS.request(f, force=True)
    return {"ok": True}


ROUTES = {
    "/api/page": page_json,
    "/api/step": step_json,
    "/api/refresh": refresh_json,
    "/api/config": lambda q: CONFIG,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, CLIENT.read_bytes(), "text/html; charset=utf-8")
        route = ROUTES.get(url.path)
        if route is None:
            return self._send(404, b"not found", "text/plain")
        try:
            body = json.dumps(route(parse_qs(url.query))).encode()
        except Exception as e:  # keep the server alive whatever a page does
            return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
        self._send(200, body, "application/json")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the console quiet


def serve(port=8040, cols=80, rows=32, open_browser=True):
    CONFIG.update(cols=max(40, min(160, cols)), rows=max(25, min(60, rows)))
    for f in pages.ALL_FEEDS:  # start loading everything straight away
        FEEDS.request(f)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"THE ORACLE is on the air at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
