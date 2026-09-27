# -*- coding: utf-8 -*-
"""The HTTP front end: the same engine, the same store, over HTTP for a browser or a script.

    POST /rpc                     the JSON-RPC 2.0 messages stdio takes, unchanged
    GET  /api/tools               the tool list
    GET  /api/<tool>?<args>       one tool: its text, and the rows behind it where the store has them
    GET  /api/graph               the whole graph as data (serve/payload.py), what an app projects from
    GET  /api/status              build sequence, backend, freshness, the project's stations
    GET  /api/changes?since=T     whether anything changed since token T (a build sequence, or the
                                  token a payload or an earlier answer carried)
    GET  /data.json               the graph payload as a file, for an app that loads one
    GET  /, /<file>               a view's files, when one is mounted

Stdlib only: a threaded `http.server`, JSON in and out, and the engine's own `ensure_fresh` before
every request, so a rebuild is served on the next call. No route writes.

Beyond one machine: the server binds to 127.0.0.1 unless told otherwise, and binding anywhere else
requires a token in the environment, OTO_SERVE_TOKEN, or it refuses to start. With a token every
request must carry it, as `Authorization: Bearer <token>` or, for a browser that opened the app,
the cookie the server sets when the page is first opened as `/?oto_token=<token>`. The token is
never written to a file or a log. Cross-origin calls are refused unless `--cors <origin>` names
the origin (or `*`), for a hosted app calling a separate server.
"""
import hmac
import json
import mimetypes
import os
import posixpath
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import payload as _payload
from ..apps import manifest as _apps

#: GET route name -> tool name; the query string carries the tool's arguments.
ROUTES = {"entity": "kg_entity", "neighbors": "kg_neighbors", "search": "kg_search", "type": "kg_by_type",
          "by-type": "kg_by_type", "count": "kg_count", "group": "kg_group_by", "explain": "kg_explain",
          "policy": "kg_policy", "overview": "kg_overview", "stale": "kg_stale", "resolve": "kg_resolve",
          "docs": "kg_docs", "pending": "kg_pending", "actions": "kg_actions"}
INTEGER_ARGS = {"n", "limit"}
BOOLEAN_ARGS = {"history", "ready", "due"}
LOOPBACK = ("127.0.0.1", "localhost", "::1")
TOKEN_ENV = "OTO_SERVE_TOKEN"
COOKIE = "oto_token"


class BindError(Exception):
    """The server refuses to start: the bind is beyond this machine and nothing would authenticate callers."""


def token_from_env(environ=None):
    """The serve token, from the environment only. Empty means none."""
    return ((environ if environ is not None else os.environ).get(TOKEN_ENV) or "").strip() or None


def check_bind(host, token):
    """Raise BindError when `host` reaches beyond this machine and there is no token."""
    if host not in LOOPBACK and not token:
        raise BindError("binding to %s would expose the store beyond this machine and nothing would authenticate "
                        "callers; set %s in the environment (never in a file) and pass it as a bearer token, "
                        "or bind to 127.0.0.1" % (host, TOKEN_ENV))


def parse_bind(text, default_host="127.0.0.1"):
    """'8765' -> (127.0.0.1, 8765); 'host:8765' -> (host, 8765)."""
    text = str(text)
    if ":" in text:
        host, port = text.rsplit(":", 1)
        return host or default_host, int(port)
    return default_host, int(text)


def _coerce(args):
    out = {}
    for key, values in args.items():
        value = values[-1] if isinstance(values, list) else values
        if key in INTEGER_ARGS:
            try:
                value = int(value)
            except ValueError:
                pass
        elif key in BOOLEAN_ARGS:
            value = str(value).lower() in ("1", "true", "yes", "on")
        out[key] = value
    return out


def make_handler(engine, app_dir=None, project_root=None, identity=None, token=None, cors=()):
    app_root = os.path.abspath(app_dir) if app_dir else None
    app_manifest = _apps.read(app_root) if app_root else None
    data_files = {e["file"].lstrip("/"): e for e in (app_manifest or {}).get("data") or []}
    overrides = _apps.override_files(app_manifest, project_root) if app_manifest else {}
    origins = tuple(o.strip().rstrip("/") for o in (cors or ()) if o and o.strip())

    def allowed_origin(origin):
        if not origin or not origins:
            return None
        if "*" in origins:
            return "*"
        return origin if origin.rstrip("/") in origins else None

    def token_matches(presented):
        return bool(presented) and hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8"))

    class Handler(BaseHTTPRequestHandler):
        server_version = "oto/" + engine.SERVER_INFO["version"]

        def log_message(self, fmt, *args):
            engine.log("http", self.address_string(), (fmt % args).replace(token, "<token>") if token else fmt % args)

        # ---- beyond one machine ----
        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            allow = allowed_origin(self.headers.get("Origin"))
            if allow:
                self.send_header("Access-Control-Allow-Origin", allow)
                self.send_header("Vary", "Origin")
            BaseHTTPRequestHandler.end_headers(self)

        def do_OPTIONS(self):
            allow = allowed_origin(self.headers.get("Origin"))
            self.send_response(204 if allow else 403)
            if allow:
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _presented_token(self):
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                name, _eq, value = part.strip().partition("=")
                if name == COOKIE:
                    return urllib.parse.unquote(value)
            return None

        def _authorised(self, parsed):
            """True when no token is required or the request carries it. A first visit from a browser,
            `GET /?oto_token=<token>`, is answered with the cookie and a redirect to the same path."""
            if not token:
                return True
            if self.command in ("GET", "HEAD"):
                query = urllib.parse.parse_qs(parsed.query)
                offered = (query.pop(COOKIE, None) or [None])[-1]
                if offered is not None:
                    if not token_matches(offered):
                        self._json(401, {"error": "wrong token"})
                        return False
                    target = parsed.path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
                    self.send_response(303)
                    self.send_header("Location", target)
                    self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (COOKIE, urllib.parse.quote(token, safe="")))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return False
            if token_matches(self._presented_token()):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="oto"')
            body = json.dumps({"error": "this server requires a token: send `Authorization: Bearer <token>`, or open the app "
                                        "as /?%s=<token> once from a browser" % COOKIE}).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return False

        # ---- responses ----
        def _json(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _text(self, status, text, content_type="text/plain; charset=utf-8"):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _file(self, path):
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        # ---- routing ----
        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            if not self._authorised(parsed):
                return None
            if parsed.path != "/rpc":
                return self._json(404, {"error": "not found; POST /rpc"})
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                req = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            if isinstance(req, list):
                answers = [m for m in (engine.respond(r) for r in req) if m is not None]
                return self._json(200, answers)
            msg = engine.respond(req)
            if msg is None:
                return self._json(204, {})
            return self._json(200, msg)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if not self._authorised(parsed):
                return None
            path = parsed.path
            args = _coerce(urllib.parse.parse_qs(parsed.query))
            if path.startswith("/api/") or path == "/data.json":
                return self._api(path, args)
            if app_root is None:
                return self._json(404, {"error": "no app mounted; the routes are under /api/ and POST /rpc",
                                        "tools": sorted(ROUTES)})
            rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
            if rel in data_files:
                return self._generated(rel)
            if rel in overrides:
                return self._file(overrides[rel])
            return self._static(path)

        def _generated(self, rel):
            """One of the app's data files, projected from the live store on each request."""
            engine.ensure_fresh()
            if engine.STORE is None:
                return self._text(503, "/* %s */" % engine.no_data_message(), "application/javascript; charset=utf-8")
            payload = _payload.build(engine.STORE, project_root, identity, passages=True, mode=engine.MODE)
            try:
                _apps.check_requires(app_manifest, payload.get("vocabulary"))
                text = _apps.render(data_files[rel], payload, app_root)
            except (_apps.AppError, ValueError) as exc:
                engine.log("app data", rel, exc)
                return self._text(500, "/* oto could not generate %s: %s */" % (rel, exc), "application/javascript; charset=utf-8")
            ctype = "application/json; charset=utf-8" if rel.endswith(".json") else "application/javascript; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            body = text.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _api(self, path, args):
            engine.ensure_fresh()
            if path == "/api/tools":
                return self._json(200, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in engine.TOOLS],
                                        "routes": {"/api/%s" % r: t for r, t in sorted(ROUTES.items())}})
            if path == "/api/status":
                store = engine.STORE
                status = {"server": engine.SERVER_NAME, "backend": engine.BACKEND, "serving": store is not None,
                          "build_seq": store.meta("build_seq") if store else None,
                          "schema_version": store.meta("schema_version") if store else None,
                          "reason": None if store else engine.no_data_message(),
                          "stations": _payload.stations(project_root), "mode": dict(engine.MODE),
                          "app": {"name": app_manifest["name"], "data": sorted(data_files)} if app_root else None}
                return self._json(200, status)
            if path == "/api/changes":
                store = engine.STORE
                seq = store.meta("build_seq") if store else None
                token = _payload.change_token(seq, engine.MODE)
                ledger = len(store.changelog(1000) or []) if store else 0
                since = args.get("since")
                changed = (str(since) not in (token, str(seq))) if since is not None else True
                return self._json(200, {"build_seq": seq, "token": token, "ledger": ledger,
                                        "stations": _payload.stations(project_root), "mode": dict(engine.MODE),
                                        "changed": changed})
            if engine.STORE is None:
                return self._json(503, {"error": engine.no_data_message()})
            if path in ("/api/graph", "/data.json"):
                passages = str(args.get("passages", "1")).lower() not in ("0", "false", "no")
                return self._json(200, _payload.build(engine.STORE, project_root, identity, passages=passages, mode=engine.MODE))
            route = path[len("/api/"):]
            tool = ROUTES.get(route)
            if not tool:
                return self._json(404, {"error": "no such route", "routes": sorted("/api/%s" % r for r in ROUTES)})
            if tool == "kg_by_type" and "type_" in args:
                args["type"] = args.pop("type_")
            msg = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
            result = msg.get("result") or {}
            text = "".join(c.get("text", "") for c in result.get("content") or [])
            if result.get("isError"):
                return self._json(400, {"tool": tool, "error": text})
            try:
                data = _payload.tool_data(engine, tool, args)
            except Exception as exc:                                    # noqa: BLE001 - the text still answers
                engine.log("tool data", tool, exc)
                data = None
            return self._json(200, {"tool": tool, "arguments": args, "text": text, "data": data})

        def _static(self, path):
            rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
            if rel in ("", "."):
                rel = "index.html"
            full = os.path.abspath(os.path.join(app_root, rel))
            if not full.startswith(app_root + os.sep) and full != app_root:
                return self._text(403, "forbidden")
            if os.path.isdir(full):
                full = os.path.join(full, "index.html")
            if not os.path.isfile(full):
                return self._text(404, "not found: %s" % rel)
            return self._file(full)

    return Handler


class Server:
    """A running HTTP front end. `serve_forever` blocks; `start` runs it on a thread (tests)."""

    def __init__(self, engine, host="127.0.0.1", port=8765, app_dir=None, project_root=None, identity=None,
                 token=None, cors=()):
        check_bind(host, token)
        self.engine = engine
        self.token = token
        self.cors = tuple(cors or ())
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, app_dir, project_root, identity, token, cors))
        self.httpd.daemon_threads = True
        self.thread = None

    @property
    def address(self):
        host, port = self.httpd.server_address[:2]
        return host, port

    @property
    def url(self):
        host, port = self.address
        return "http://%s:%d" % (host, port)

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def serve_forever(self):
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.httpd.server_close()


def serve(engine, bind, app_dir=None, project_root=None, identity=None, token=None, cors=()):
    """Run the front end until interrupted. Raises BindError for a bind beyond this machine with no token."""
    host, port = parse_bind(bind)
    server = Server(engine, host, port, app_dir=app_dir, project_root=project_root, identity=identity, token=token, cors=cors)
    engine.log("http: serving on %s%s%s%s" % (server.url, (" with app %s" % app_dir) if app_dir else "",
                                              " (token required)" if token else "",
                                              (" cors=%s" % ",".join(server.cors)) if server.cors else ""))
    print("oto serve: %s  (POST /rpc, GET /api/graph, GET /api/status%s)%s" % (
        server.url, ", GET / for the app" if app_dir else "",
        "\n  a token is required on every call: Authorization: Bearer <%s>, or open /?%s=<token> once in a browser"
        % (TOKEN_ENV, COOKIE) if token else ""), file=sys.stderr, flush=True)
    if host not in LOOPBACK:
        engine.log("WARNING: bound to %s, reachable beyond this machine; every call must carry the token" % host)
    server.serve_forever()
    return server
