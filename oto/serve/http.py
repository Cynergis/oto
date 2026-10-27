# -*- coding: utf-8 -*-
"""The HTTP front end: the same engine, the same store, over HTTP for a browser or a script.

    POST /rpc                     the JSON-RPC 2.0 messages stdio takes, unchanged
    GET  /api/tools               the tool list
    GET  /api/<tool>?<args>       one tool: its text, and the rows behind it where the store has them
    GET  /api/graph               the whole graph as data (serve/payload.py), what an app projects from
    GET  /api/ontology            the ontology as a navigable model (serve/ontology.py); ?class=<Name> for one class
    GET  /api/status              build sequence, backend, freshness, the project's stations, and the
                                  workbench snapshot (oto/snapshot.py) under `snapshot`
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
never written to a file or a log. Who asks, for the tools the policy holds to a principal (`kg_read`
on a graph whose vocabulary declares PolicyRule, roadmap E5), comes from `X-Oto-Principal:
principal.<id>` and, for an agent, `X-Oto-Agent: agent.<id>`; stdio reads OTO_PRINCIPAL and OTO_AGENT. Cross-origin calls are refused unless `--cors <origin>` names
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

from ..project import ProjectError
from . import graphs as _graphs, lexicon as _lexicon, links as _links, ontology as _ontology, payload as _payload, rules as _rules, versions as _versions
from .. import snapshot as _snapshot
from ..apps import manifest as _apps
from ..apps import studio as _studio

#: GET route name -> tool name; the query string carries the tool's arguments.
ROUTES = {"entity": "kg_entity", "neighbors": "kg_neighbors", "search": "kg_search", "type": "kg_by_type",
          "by-type": "kg_by_type", "count": "kg_count", "group": "kg_group_by", "explain": "kg_explain",
          "policy": "kg_policy", "overview": "kg_overview", "stale": "kg_stale", "resolve": "kg_resolve",
          "docs": "kg_docs", "pending": "kg_pending", "tools": "kg_tools", "actions": "kg_actions", "define": "kg_define",
          "questions": "kg_questions", "ask": "kg_ask", "brief": "kg_brief", "dependencies": "kg_dependencies", "call": "kg_call", "read": "kg_read", "arch-context": "arch_context"}
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


def _mount(prefix, app_dir, project_root):
    """One view served under /<prefix>/ ("" for the root): its directory, manifest, data files, overrides."""
    root = os.path.abspath(app_dir)
    manifest = _apps.read(root)
    return {"prefix": prefix.strip("/"), "root": root, "manifest": manifest,
            "data": {e["file"].lstrip("/"): e for e in manifest.get("data") or []},
            "overrides": _apps.override_files(manifest, project_root)}


#: One store, one connection, many request threads: the requests that read the store take turns. Two
#: data files of one page (a view's own and the studio's) are asked for at once on every load.
_STORE_LOCK = threading.RLock()


def make_handler(engine, app_dir=None, project_root=None, identity=None, token=None, cors=(), mounts=None, catalog=None):
    """`app_dir` is served at /; each of `mounts`, [(name, directory)], at /<name>/ with its own data
    files, so a project's views sit side by side under one home page; `catalog` is served as
    /views.json for that page. A view's relative addresses (data.json, api/...) resolve under its prefix."""
    mounted = ([_mount("", app_dir, project_root)] if app_dir else []) + \
        [_mount(name, directory, project_root) for name, directory in (mounts or [])]
    by_prefix = {m["prefix"]: m for m in mounted}
    studio_views = list(mounts or [])
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
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Oto-Principal, X-Oto-Agent")
                self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _caller(self):
            """Who asks, from X-Oto-Principal and X-Oto-Agent (roadmap E5); empty when the headers are absent."""
            out = {}
            for key, header in (("principal", "X-Oto-Principal"), ("agent", "X-Oto-Agent")):
                value = (self.headers.get(header) or "").strip()
                if value:
                    out[key] = value
            return out

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
            caller = self._caller()
            with _STORE_LOCK:
                if isinstance(req, list):
                    answers = [m for m in (engine.respond(r, caller=caller) for r in req) if m is not None]
                    return self._json(200, answers)
                msg = engine.respond(req, caller=caller)
            if msg is None:
                return self._json(204, {})
            return self._json(200, msg)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if not self._authorised(parsed):
                return None
            path = parsed.path
            args = _coerce(urllib.parse.parse_qs(parsed.query))
            if catalog is not None and path == "/views.json":
                return self._json(200, catalog)
            if path == "/" + _studio.KIT_PREFIX or path.startswith("/%s/" % _studio.KIT_PREFIX):
                with _STORE_LOCK:
                    return self._studio(path[len(_studio.KIT_PREFIX) + 1:].lstrip("/"))
            mount, rest = self._mount_for(path)
            if mount is not None and mount["prefix"] and rest == "":
                return self._redirect(path + "/")          # relative addresses resolve under the slash
            if rest.startswith("/api/") or rest == "/data.json":
                with _STORE_LOCK:
                    return self._api(rest, args)
            if mount is None:
                return self._json(404, {"error": "no app mounted; the routes are under /api/ and POST /rpc",
                                        "tools": sorted(ROUTES)})
            rel = posixpath.normpath(urllib.parse.unquote(rest)).lstrip("/")
            if rel in mount["data"]:
                with _STORE_LOCK:
                    return self._generated(mount, rel)
            if rel in mount["overrides"]:
                return self._file(mount["overrides"][rel])
            return self._static(mount, rest)

        def _mount_for(self, path):
            """(the view a path belongs to, the path inside it): /<name>/... for a mounted view, else the root's."""
            first, slash, remainder = path.lstrip("/").partition("/")
            if first and first in by_prefix and by_prefix[first]["prefix"]:
                return by_prefix[first], ("/" + remainder) if slash else ""
            return by_prefix.get(""), path

        def _redirect(self, location):
            self.send_response(301)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _generated(self, mount, rel):
            """One of a view's data files, projected from the live store on each request."""
            engine.ensure_fresh()
            if engine.STORE is None:
                return self._text(503, "/* %s */" % engine.no_data_message(), "application/javascript; charset=utf-8")
            payload = _payload.build(engine.STORE, project_root, identity, passages=True, mode=engine.MODE)
            try:
                _apps.check_requires(mount["manifest"], payload.get("vocabulary"))
                text = _apps.render(mount["data"][rel], payload, mount["root"])
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
                routes = {"/api/%s" % r: t for r, t in sorted(ROUTES.items())}
                routes.update({"/api/graph": "the whole graph as data", "/api/ontology": "the ontology as a model (?class=<Name> for one class)",
                               "/api/ontology/diff": "the vocabulary at a git ref against the working tree or another ref (?from=<ref>&to=<ref>)",
                               "/api/rules": "the rules as a person reads them (?class=<Name> for those that apply to one class)",
                               "/api/lexicon": "every term in every language and the words people use (?q=<words> to search)",
                               "/api/graphs": "this graph and the graphs it depends on, near-duplicates flagged (?graph=<id> for one)",
                               "/api/links": "what bears on one entity: rules, terms, graphs, decisions, files (?entity=<id>)",
                               "/api/status": "the server and the project", "/api/changes": "what moved since a token"})
                return self._json(200, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in engine.TOOLS], "routes": routes})
            if path == "/api/status":
                store = engine.STORE
                status = {"server": engine.SERVER_NAME, "backend": engine.BACKEND, "serving": store is not None,
                          "build_seq": store.meta("build_seq") if store else None,
                          "schema_version": store.meta("schema_version") if store else None,
                          "reason": None if store else engine.no_data_message(),
                          "stations": _payload.stations(project_root), "mode": dict(engine.MODE),
                          "app": {"name": by_prefix[""]["manifest"]["name"], "data": sorted(by_prefix[""]["data"])}
                          if "" in by_prefix else None,
                          "views": [m["prefix"] for m in mounted if m["prefix"]],
                          "snapshot": _snapshot.for_root(project_root)}
                return self._json(200, status)
            if path == "/api/changes":
                store = engine.STORE
                seq = store.meta("build_seq") if store else None
                token = _payload.change_token(seq, engine.MODE)
                ledger = len(store.changelog(1000) or []) if store else 0
                since = args.get("since")
                changed = (str(since) not in (token, str(seq))) if since is not None else True
                current = _snapshot.for_root(project_root)
                return self._json(200, {"build_seq": seq, "token": token, "ledger": ledger,
                                        "stations": _payload.stations(project_root), "mode": dict(engine.MODE),
                                        "changed": changed, "snapshot_token": current and current["token"]})
            if engine.STORE is None:
                return self._json(503, {"error": engine.no_data_message()})
            if path in ("/api/graph", "/data.json"):
                passages = str(args.get("passages", "1")).lower() not in ("0", "false", "no")
                return self._json(200, _payload.build(engine.STORE, project_root, identity, passages=passages, mode=engine.MODE))
            if path == "/api/ontology/diff":
                if "from" not in args:
                    return self._json(400, {"error": "say which ref to compare from: /api/ontology/diff?from=<ref>[&to=<ref>]"})
                if not project_root:
                    return self._json(400, {"error": "no project beside this store: a ref needs the project's git repository"})
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                try:
                    result = _versions.diff_refs(str(args["from"]), str(args["to"]) if args.get("to") else None, cwd=project_root,
                                                 nodes=payload["nodes"], edges=payload["edges"])
                except (ProjectError, OSError, ValueError) as exc:
                    return self._json(400, {"error": str(exc)})
                return self._json(200, result)
            if path == "/api/ontology":
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                m = payload["ontology"]
                if "class" in args:
                    one = _ontology.for_class(m, str(args["class"]))
                    if one is None:
                        return self._json(404, {"error": "the ontology declares no class %r" % args["class"], "classes": [c["name"] for c in m["classes"]]})
                    return self._json(200, one)
                return self._json(200, m)
            if path == "/api/rules":
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                m = payload["rules"]
                if "class" in args:
                    one = _rules.for_class(m, str(args["class"]))
                    if one is None:
                        return self._json(404, {"error": "the ontology declares no class %r" % args["class"], "classes": sorted(m["by_class"])})
                    return self._json(200, one)
                return self._json(200, m)
            if path == "/api/graphs":
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                m = payload["graphs"]
                if "graph" in args:
                    one = _graphs.for_graph(m, str(args["graph"]))
                    if one is None:
                        return self._json(404, {"error": "no descriptor %r here" % args["graph"], "graphs": [g["id"] for g in m["graphs"]]})
                    return self._json(200, one)
                return self._json(200, m)
            if path == "/api/links":
                if "entity" not in args:
                    return self._json(400, {"error": "say which entity: /api/links?entity=<id>"})
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                links = _links.for_entity(payload, str(args["entity"]))
                if links is None:
                    return self._json(404, {"error": "no entity %r here" % args["entity"]})
                return self._json(200, links)
            if path == "/api/lexicon":
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, ledger=0, mode=engine.MODE)
                m = payload["terms"]
                if "q" in args:
                    return self._json(200, {"query": str(args["q"]), "hits": _lexicon.search(m, str(args["q"]))})
                return self._json(200, m)
            route = path[len("/api/"):]
            tool = ROUTES.get(route)
            if not tool:
                return self._json(404, {"error": "no such route", "routes": sorted("/api/%s" % r for r in ROUTES)})
            if tool == "kg_by_type" and "type_" in args:
                args["type"] = args.pop("type_")
            msg = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, caller=self._caller())
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

        def _studio(self, rel):
            """The kit every view of the studio includes, and its data from the live store."""
            if rel != _studio.DATA_NAME:
                return self._static({"root": os.path.abspath(_studio.KIT_DIR)}, "/" + rel)
            engine.ensure_fresh()
            if engine.STORE is None:
                text = "window.__STUDIO__ = null;\n"
            else:
                payload = _payload.build(engine.STORE, project_root, identity, passages=False, mode=engine.MODE)
                rows = engine.questions_data().get("rows") or []
                text = _studio.script(_studio.data(studio_views, payload, rows, identity))
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _static(self, mount, path):
            app_root = mount["root"]
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
                 token=None, cors=(), mounts=None, catalog=None):
        check_bind(host, token)
        self.engine = engine
        self.token = token
        self.cors = tuple(cors or ())
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, app_dir, project_root, identity, token, cors,
                                                                    mounts=mounts, catalog=catalog))
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


def serve(engine, bind, app_dir=None, project_root=None, identity=None, token=None, cors=(), mounts=None, catalog=None):
    """Run the front end until interrupted. Raises BindError for a bind beyond this machine with no token."""
    host, port = parse_bind(bind)
    server = Server(engine, host, port, app_dir=app_dir, project_root=project_root, identity=identity, token=token, cors=cors,
                    mounts=mounts, catalog=catalog)
    engine.log("http: serving on %s%s%s%s" % (server.url, (" with app %s" % app_dir) if app_dir else "",
                                              " (token required)" if token else "",
                                              (" cors=%s" % ",".join(server.cors)) if server.cors else ""))
    print("oto serve: %s  (POST /rpc, GET /api/graph, GET /api/status%s)%s" % (
        server.url, (", GET / for the home page, and %s" % ", ".join("/%s/" % n for n, _d in mounts)) if mounts
        else (", GET / for the app" if app_dir else ""),
        "\n  a token is required on every call: Authorization: Bearer <%s>, or open /?%s=<token> once in a browser"
        % (TOKEN_ENV, COOKIE) if token else ""), file=sys.stderr, flush=True)
    if host not in LOOPBACK:
        engine.log("WARNING: bound to %s, reachable beyond this machine; every call must carry the token" % host)
    server.serve_forever()
    return server
