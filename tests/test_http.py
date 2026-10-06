"""The HTTP front end and the static site: the same engine and store over HTTP, the graph as
data, the app mount, hot reload, and the site stage inside the build transaction."""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import pytest

from oto.builder import build, generated_paths
from oto.cli import main
from oto.project import Project, ProjectError
from oto.scaffold import init
from oto.serve import payload as _payload
from oto.serve.store import SqliteStore

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _project(root):
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    project = Project.standard(root)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)
    with open(os.path.join(root, "notes", "ledger.md"), "w", encoding="utf-8") as f:
        f.write("# The ledger\n\nThe payments ledger records every transfer.\n")
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "payments", "targets": ["system.payments"], "status": "current", "note": ""}]}, f)
    build(project)
    return project


def _engine(project):
    """A fresh engine module bound to this project's store (the module keeps global state)."""
    import importlib
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine
    importlib.reload(engine)
    return engine


def _get(url, expect=200):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def _rpc(url, body):
    req = urllib.request.Request(url + "/rpc", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


@pytest.fixture
def served():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        app = os.path.join(root, "app")
        os.makedirs(os.path.join(app, "assets"))
        with open(os.path.join(app, "index.html"), "w", encoding="utf-8") as f:
            f.write("<title>Acme reader</title><script src=\"assets/app.js\"></script>")
        with open(os.path.join(app, "assets", "app.js"), "w", encoding="utf-8") as f:
            f.write("fetch('data.json')")
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=app, project_root=root, identity=project.config()).start()
        try:
            yield project, engine, server
        finally:
            server.stop()


def test_rpc_over_http_equals_stdio_byte_for_byte(served):
    project, engine, server = served
    calls = [{"name": "kg_entity", "arguments": {"term": "system.payments"}},
             {"name": "kg_explain", "arguments": {"term": "system.payments"}},
             {"name": "kg_overview", "arguments": {"limit": 5}},
             {"name": "kg_resolve", "arguments": {"term": "payments"}},
             {"name": "kg_search", "arguments": {"query": "ledger"}}]
    for number, call in enumerate(calls, 1):
        req = {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": call}
        assert _rpc(server.url, req) == engine.respond(req), call["name"]
    listing = _rpc(server.url, {"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    assert [t["name"] for t in listing["result"]["tools"]] == [t["name"] for t in engine.TOOLS]
    assert _rpc(server.url, {"jsonrpc": "2.0", "id": 10, "method": "nope"})["error"]["code"] == -32601
    # a batch, and a notification that gets no reply
    batch = _rpc(server.url, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert batch == [{"jsonrpc": "2.0", "id": 1, "result": {}}]


def test_get_routes_carry_the_text_and_the_rows(served):
    project, engine, server = served
    status, ctype, body = _get(server.url + "/api/entity?term=system.payments")
    assert status == 200 and ctype.startswith("application/json")
    answer = json.loads(body)
    assert answer["tool"] == "kg_entity" and "[System — " in answer["text"]
    node = answer["data"]["node"]
    assert node["id"] == "system.payments" and isinstance(node["attributes"], dict) and node["evidence"] == []
    assert any(e["rel"] == "part_of" for e in answer["data"]["edges_in"])
    status, _c, body = _get(server.url + "/api/type?type=Component&limit=1")
    assert status == 200 and len(json.loads(body)["data"]["rows"]) == 1
    status, _c, body = _get(server.url + "/api/count?type=System")
    assert json.loads(body)["data"]["count"] == 1 and "count = 1" in json.loads(body)["text"]
    status, _c, body = _get(server.url + "/api/explain?term=system.payments")
    assert json.loads(body)["data"]["derived_edges"][0]["premises"], "premises come back parsed"
    status, _c, body = _get(server.url + "/api/define?term=part%20of")
    answer = json.loads(body)
    assert status == 200 and answer["tool"] == "kg_define" and "inverse: contains" in answer["text"]
    assert answer["data"]["terms"][0]["name"] == "part_of" and answer["data"]["terms"][0]["labels"] == {"en": "part of"}
    status, _c, body = _get(server.url + "/api/tools")
    assert "/api/entity" in json.loads(body)["routes"]
    status, _c, body = _get(server.url + "/api/nothing")
    assert status == 404 and "/api/entity" in json.loads(body)["routes"]
    status, _c, body = _get(server.url + "/api/entity")           # a missing argument is a tool error, not a crash
    assert status == 400 and json.loads(body)["tool"] == "kg_entity"


def test_the_graph_payload_is_the_whole_store_as_data(served):
    project, engine, server = served
    status, _c, body = _get(server.url + "/api/graph")
    payload = json.loads(body)
    assert payload["payload_version"] == 1 and payload["backend"] == "sqlite" and payload["build_seq"]
    assert payload["project"]["slug"] == "acme" and "System" in payload["vocabulary"]["classes"]
    ids = {n["id"] for n in payload["nodes"]}
    assert "system.payments" in ids and "doc.handbook" in ids
    ledger = next(n for n in payload["nodes"] if n["id"] == "datastore.ledger")
    assert isinstance(ledger["attributes"], dict) and isinstance(ledger["tags"], list) and "degree" in ledger
    derived = [e for e in payload["edges"] if e["status"] == "derived"]
    assert derived and derived[0]["derived_by"] and isinstance(derived[0]["premises"], list)
    assert any(e["from"] == "datastore.ledger" and e["rel"] == "part_of" for e in payload["edges"])
    assert payload["findings"] and payload["findings"][0]["rule"]
    assert payload["lexicon"][0]["phrase"] == "payments"
    assert payload["counts"]["by_class"]["System"] == 1 and payload["counts"]["nodes"] == len(payload["nodes"])
    assert payload["stations"] == {"inbox": 0, "processing": 0, "errors": 0, "archive": 0}
    assert any(p["path"] == "notes/ledger.md" for p in payload["passages"])
    status, _c, body = _get(server.url + "/data.json?passages=0")
    assert "passages" not in json.loads(body)
    # the same function, the same object, from a store opened directly
    store = SqliteStore(project.layout.database)
    try:
        direct = _payload.build(store, os.path.dirname(project.src), project.config())
    finally:
        store.close()
    assert direct == payload


def test_the_app_is_served_and_cannot_escape_its_directory(served):
    project, engine, server = served
    status, ctype, body = _get(server.url + "/")
    assert status == 200 and ctype.startswith("text/html") and b"Acme reader" in body
    status, ctype, body = _get(server.url + "/assets/app.js")
    assert status == 200 and "javascript" in ctype
    status, _c, _b = _get(server.url + "/missing.css")
    assert status == 404
    status, _c, _b = _get(server.url + "/../project.config.json")
    assert status in (403, 404)
    status, _c, body = _get(server.url + "/api/status")
    s = json.loads(body)
    assert s["serving"] and s["backend"] == "sqlite" and s["app"] == {"name": "app", "data": []} and s["stations"]["inbox"] == 0


def test_hot_reload_and_the_change_signal(served):
    project, engine, server = served
    status, _c, body = _get(server.url + "/api/changes")
    before = json.loads(body)["build_seq"]
    status, _c, body = _get(server.url + "/api/changes?since=%s" % before)
    assert json.loads(body)["changed"] is False
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["nodes"].append({"id": "system.new", "type": "System", "label": "Brand new system", "aliases": [], "summary": "s",
                           "attributes": {}, "tags": [], "as_of": "2026-09-19", "valid_from": "2026-09-19",
                           "source_doc": "sample", "status": "current", "sources": ["sample"]})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    import time
    time.sleep(0.05)
    build(project)
    status, _c, body = _get(server.url + "/api/entity?term=system.new")
    assert status == 200 and "Brand new system" in json.loads(body)["text"], "the rebuilt store is served with no restart"


def test_without_an_app_the_root_explains_the_routes():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0).start()
        try:
            status, _c, body = _get(server.url + "/")
            assert status == 404 and "entity" in json.loads(body)["tools"]
            assert server.address[0] == "127.0.0.1"
        finally:
            server.stop()


def test_parse_bind():
    from oto.serve.http import parse_bind
    assert parse_bind("8765") == ("127.0.0.1", 8765)
    assert parse_bind("0.0.0.0:80") == ("0.0.0.0", 80)
    assert parse_bind(":9000") == ("127.0.0.1", 9000)


def test_serve_http_from_the_command_line_and_refuses_a_bad_app():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        env = dict(os.environ, PYTHONPATH=REPO)
        env.pop("OTO_STORE", None)
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root, "--http", "0", "--view", "/nowhere/x"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 1 and "not a directory" in r.stderr


# ---- the site stage ----

def test_site_stage_writes_the_payload_and_copies_the_app():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        assert not os.path.exists(project.layout.site), "not targeted, not written"
        app = os.path.join(root, "app")
        os.makedirs(os.path.join(app, ".git"))
        with open(os.path.join(app, "index.html"), "w", encoding="utf-8") as f:
            f.write("<title>App</title>")
        assert main(["build", "--project", root, "--target", "site", "--view", app]) == 0
        site = project.layout.site
        assert os.path.exists(os.path.join(site, "index.html")) and not os.path.exists(os.path.join(site, ".git"))
        with open(os.path.join(site, "data.json"), encoding="utf-8") as f:
            payload = json.load(f)
        store = SqliteStore(project.layout.database)
        try:
            assert payload == _payload.build(store, root, project.config())
        finally:
            store.close()
        assert site in generated_paths(project)
        assert main(["build", "--project", root, "--target", "site", "--view", "/nowhere"]) == 1


def test_site_config_drives_the_stage_and_passages_can_be_dropped(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        cfg = project.config()
        cfg["targets"] = ["sqlite", "site"]
        cfg["site"] = {"passages": False}
        with open(project.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        build(project)
        out = capsys.readouterr().out
        assert "site:" in out and "with app explorer" in out
        assert os.path.exists(os.path.join(project.layout.site, "explorer.js")), "the explorer is the default app"
        with open(os.path.join(project.layout.site, "data.json"), encoding="utf-8") as f:
            assert "passages" not in json.load(f)


def test_a_failed_build_restores_the_previous_site():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        project.options = {"targets": {"site"}, "verify": False, "view": None}
        build(project)
        marker = os.path.join(project.layout.site, "data.json")
        first = open(marker, encoding="utf-8").read()
        project.options = {"targets": {"site"}, "verify": False, "view": "/nowhere/at/all"}   # the site stage fails
        with pytest.raises(ProjectError, match="not a directory"):
            build(project)
        assert open(marker, encoding="utf-8").read() == first, "the transaction put the site back"


def test_publish_site_carries_the_site_beside_the_store(capsys):
    from oto import publish as pub
    with tempfile.TemporaryDirectory() as root:
        project = _project(os.path.join(root, "p"))
        bare = os.path.join(root, "query.git")
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", bare], check=True)
        with pytest.raises(ProjectError, match="needs build/site"):
            pub.publish(project, bare, site=True)
        project.options = {"targets": {"site"}, "verify": False, "view": None}
        build(project)
        manifest = pub.publish(project, bare, site=True)
        assert manifest["changed"] and manifest["site"] is True
        listing = subprocess.run(["git", "--git-dir", bare, "ls-tree", "-r", "--name-only", "main"],
                                 capture_output=True, text=True, check=True).stdout.split()
        assert "site/data.json" in listing and "acme.db" in listing
        assert pub.publish(project, bare, site=True)["changed"] is False


# ---- beyond one machine: the token, the cookie hand-off, CORS, the bind rule ----

def _request(url, headers=None, method="GET", body=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_a_token_guards_every_route_and_a_browser_gets_a_cookie_once():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        app = os.path.join(root, "app")
        os.makedirs(app)
        with open(os.path.join(app, "index.html"), "w", encoding="utf-8") as f:
            f.write("<title>Acme</title>")
        logged = []
        engine.log = lambda *a: logged.append(" ".join(str(x) for x in a))
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=app, project_root=root, identity=project.config(),
                              token="s3cret-token").start()
        try:
            url = server.url
            for path in ("/api/status", "/api/graph", "/data.json", "/", "/api/entity?term=Payments"):
                status, headers, body = _request(url + path)
                assert status == 401 and "Bearer" in headers.get("WWW-Authenticate", ""), path
                assert "Authorization: Bearer" in json.loads(body)["error"]
            status, _h, _b = _request(url + "/rpc", method="POST", body=b"{}", headers={"Content-Type": "application/json"})
            assert status == 401
            bearer = {"Authorization": "Bearer s3cret-token"}
            status, _h, body = _request(url + "/api/status", headers=bearer)
            assert status == 200 and json.loads(body)["serving"] is True
            status, _h, _b = _request(url + "/api/status", headers={"Authorization": "Bearer wrong"})
            assert status == 401
            # the browser's first visit: the token in the query once, then a cookie, then plain requests
            status, headers, _b = _request(url + "/?oto_token=s3cret-token")
            assert status == 303 and headers["Location"] == "/" and headers["Set-Cookie"].startswith("oto_token=s3cret-token; Path=/; HttpOnly")
            cookie = {"Cookie": headers["Set-Cookie"].split(";")[0]}
            status, _h, body = _request(url + "/", headers=cookie)
            assert status == 200 and b"Acme" in body
            status, _h, body = _request(url + "/data.json", headers=cookie)
            assert status == 200 and json.loads(body)["build_seq"]
            status, headers, _b = _request(url + "/api/entity?term=Payments&oto_token=s3cret-token")
            assert status == 303 and headers["Location"] == "/api/entity?term=Payments", "the token leaves the query string"
            status, _h, _b = _request(url + "/?oto_token=nope")
            assert status == 401
            assert not any("s3cret-token" in line for line in logged), "the token is never logged"
            assert any("<token>" in line for line in logged)
        finally:
            server.stop()


def test_cors_is_off_unless_an_origin_is_named():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        closed = _http.Server(engine, "127.0.0.1", 0, project_root=root).start()
        try:
            status, headers, _b = _request(closed.url + "/api/status", headers={"Origin": "https://app.example"})
            assert status == 200 and "Access-Control-Allow-Origin" not in headers
            status, headers, _b = _request(closed.url + "/api/status", method="OPTIONS", headers={"Origin": "https://app.example"})
            assert status == 403 and "Access-Control-Allow-Methods" not in headers
        finally:
            closed.stop()
        opened = _http.Server(engine, "127.0.0.1", 0, project_root=root, cors=["https://app.example/"]).start()
        try:
            status, headers, _b = _request(opened.url + "/api/status", headers={"Origin": "https://app.example"})
            assert status == 200 and headers["Access-Control-Allow-Origin"] == "https://app.example" and headers["Vary"] == "Origin"
            status, headers, _b = _request(opened.url + "/rpc", method="OPTIONS", headers={"Origin": "https://app.example"})
            assert status == 204 and headers["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
            assert "Authorization" in headers["Access-Control-Allow-Headers"]
            status, headers, _b = _request(opened.url + "/api/status", headers={"Origin": "https://other.example"})
            assert status == 200 and "Access-Control-Allow-Origin" not in headers
            status, headers, _b = _request(opened.url + "/api/status")
            assert headers["X-Content-Type-Options"] == "nosniff"
        finally:
            opened.stop()
        anywhere = _http.Server(engine, "127.0.0.1", 0, project_root=root, cors=["*"]).start()
        try:
            status, headers, _b = _request(anywhere.url + "/api/status", headers={"Origin": "https://other.example"})
            assert headers["Access-Control-Allow-Origin"] == "*"
        finally:
            anywhere.stop()


def test_binding_beyond_this_machine_needs_the_token():
    from oto.serve import http as _http
    with pytest.raises(_http.BindError) as exc:
        _http.check_bind("0.0.0.0", None)
    assert "OTO_SERVE_TOKEN" in str(exc.value) and "never in a file" in str(exc.value)
    _http.check_bind("0.0.0.0", "t")
    _http.check_bind("127.0.0.1", None)
    _http.check_bind("localhost", None)
    assert _http.token_from_env({}) is None and _http.token_from_env({"OTO_SERVE_TOKEN": " x "}) == "x"
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        env = dict(os.environ, PYTHONPATH=REPO)
        env.pop("OTO_STORE", None)
        env.pop("OTO_SERVE_TOKEN", None)
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root, "--http", "0.0.0.0:0"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 1 and "refused" in r.stderr and "OTO_SERVE_TOKEN" in r.stderr
