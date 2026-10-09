"""The pending lane and the preview: what is on its way into the graph, by station; the tool
that lists it; the store the graph would be if it all went through; and the server that
rebuilds that store on every change."""
import json
import os
import subprocess
import sys
import tempfile
import time

import pytest

from oto import preview as _preview
from oto.builder import build
from oto.cli import main
from oto.curate import pending as _pending
from oto.project import Project
from oto.scaffold import init
from oto.serve import payload as _payload
from oto.serve.store import SqliteStore

from test_apps import _engine, _get

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = {"id": "system.billing", "type": "System", "label": "Billing platform", "aliases": [], "summary": "Bills customers.",
       "attributes": {}, "tags": [], "as_of": "2026-09-01", "valid_from": "2026-09-01", "source_doc": "memo",
       "status": "current", "sources": ["memo"], "evidence": [{"doc": "memo", "where": "p.1", "quote": "Billing bills."}]}


def _project(root):
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    project = Project.standard(root)
    build(project)
    return project


def _write(root, name, payload):
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


# ---- the lane ----

def test_nothing_pending_on_a_fresh_project():
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        p = _pending.collect(root)
        assert p["rows"] == [] and p["differs"] == 0 and p["stations"]["candidate"] is False and p["stations"]["proposals"] == 0
        assert "Nothing is pending" in _pending.text(p)


def test_proposals_and_the_candidate_are_listed_by_station_with_verdicts():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        # a proposal that adds a system and an edge, one that repeats a fact, one refused, one unreadable
        _write(root, "proposals/memo.json", {"source_doc": "memo", "as_of": "2026-09-01", "nodes": [NEW],
                                              "edges": [{"from": "system.billing", "rel": "owned_by", "to": "team.payments"},
                                                        {"from": "system.billing", "rel": "depends_on", "to": "system.ghost"}]})
        _write(root, "proposals/repeat.json", {"source_doc": "review", "nodes": [{"id": "system.payments", "type": "System",
                                                                                   "label": "Payments platform"}], "edges": []})
        _write(root, "proposals/wrong.json", {"source_doc": "rumour", "nodes": [{"id": "system.payments", "type": "System",
                                                                                  "label": "Payments platform (renamed)"}], "edges": []})
        with open(os.path.join(root, "proposals", "broken.json"), "w", encoding="utf-8") as f:
            f.write("not json")
        # and an open candidate that retires a component and adds an edge
        assert main(["curate", "start", "--project", root]) == 0
        cand = json.load(open(os.path.join(root, "graph.candidate.json"), encoding="utf-8"))
        for n in cand["nodes"]:
            if n["id"] == "component.settlement-job":
                n["status"] = "superseded"; n["valid_to"] = "2026-09-01"; n["superseded_by"] = "component.payment-api"
        cand["edges"].append({"from": "component.payment-api", "rel": "consumes", "to": "interface.payments-v2"})
        _write(root, "graph.candidate.json", cand)

        p = _pending.collect(root, today="2026-09-02")
        assert p["stations"]["candidate"] is True and p["stations"]["proposals"] == 4
        by = {}
        for r in p["rows"]:
            by.setdefault((r["station"], r["verdict"]), []).append(r)
        assert [r["id"] for r in by[("candidate", "retire")]] == ["component.settlement-job"]
        assert [(r["from"], r["rel"], r["to"]) for r in by[("candidate", "new")]] == [("component.payment-api", "consumes", "interface.payments-v2")]
        new = [r for r in by[("proposal", "new")] if r["kind"] == "node"]
        assert [r["id"] for r in new] == ["system.billing"] and new[0]["source"] == "proposals/memo.json" and new[0]["evidence"]
        edges = [r for r in by[("proposal", "new")] if r["kind"] == "edge"]
        assert {(e["rel"], e.get("reason")) for e in edges} == {("owned_by", None), ("depends_on", "points at a node not in the graph yet")}
        refused = by[("proposal", "refused")]
        assert {r["source"] for r in refused} == {"proposals/wrong.json", "proposals/broken.json"}
        assert any("supersession" in (r.get("reason") or "") for r in refused)
        assert not any(r.get("id") == "system.payments" and r["verdict"] == "new" for r in p["rows"]), "a repeated fact is not pending"
        assert p["counts"] == {"candidate": 2, "proposal": 3, "refused": 2}
        assert p["differs"] == 5
        text = _pending.text(p)
        assert "candidate    open: 2 change(s)" in text and "3 fact(s) would be added, 2 refused" in text
        assert "retire   Settlement job" in text and "refused  " in text and "not in the graph yet" in text
        # the composed graph is what the preview builds
        ids = {n["id"] for n in p["composed"]["nodes"]}
        assert "system.billing" in ids and "system.ghost" not in ids


def test_the_pending_tool_and_the_payload_carry_the_lane():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _write(root, "proposals/memo.json", {"source_doc": "memo", "nodes": [NEW], "edges": []})
        engine = _engine(project)
        assert engine.PROJECT_ROOT == os.path.realpath(root) or engine.PROJECT_ROOT == root
        text = engine.pending_text()
        assert "proposal (1):" in text and "Billing platform" in text
        assert any(t["name"] == "kg_pending" for t in engine.TOOLS)
        store = SqliteStore(project.layout.database)
        try:
            payload = _payload.build(store, root, project.config())
        finally:
            store.close()
        assert payload["pending"][0]["id"] == "system.billing" and payload["pending"][0]["station"] == "proposal"
        assert payload["mode"] == {"regime": "live"} and payload["token"].startswith(str(payload["build_seq"]))
        # a store served without its project cannot know
        os.environ["OTO_PROJECT_CONFIG"] = "/nowhere/project.config.json"
        import importlib
        from oto.serve import engine as fresh
        importlib.reload(fresh)
        assert fresh.PROJECT_ROOT is None and "not known here" in fresh.pending_text()
        r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root, "pending"], cwd=REPO,
                           env=dict(os.environ, PYTHONPATH=REPO), capture_output=True, text=True)
        assert r.returncode == 0 and "Billing platform" in r.stdout


# ---- the preview ----

def test_preview_builds_the_graph_as_it_would_be_and_leaves_the_live_store_alone(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        live_db = project.layout.database
        before = os.stat(live_db).st_mtime_ns
        _write(root, "proposals/memo.json", {"source_doc": "memo", "nodes": [NEW],
                                              "edges": [{"from": "system.billing", "rel": "owned_by", "to": "team.payments"},
                                                        {"from": "datastore.ledger", "rel": "part_of", "to": "system.billing"}]})
        assert main(["preview", "--project", root, "--show"]) == 0
        assert "Billing platform" in capsys.readouterr().out
        assert main(["preview", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "preview:" in out and "1 proposed" in out or "proposed fact" in out
        db = _preview.database(project)
        assert os.path.exists(db) and os.stat(live_db).st_mtime_ns == before, "the live store is untouched"
        meta = _preview.read_meta(project)
        assert meta["differs"] == 3 and meta["counts"]["proposal"] == 3 and meta["nodes"] == 49
        store = SqliteStore(db)
        try:
            assert store.node("system.billing")["label"] == "Billing platform"
            derived = [e for e in store.all_edges() if e["status"] == "derived"]
            assert any(e["dst"] == "system.billing" and e["rel"] == "threatens" for e in derived), \
                "rules ran on the composed graph: the ledger's risk reaches the new system"
            assert any(p["path"] == "documents/" or p["path"].startswith("entities/") for p in store.passages())
        finally:
            store.close()
        live = SqliteStore(live_db)
        try:
            assert live.node("system.billing") is None
        finally:
            live.close()


def test_serve_preview_and_watch_rebuild_on_change():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _preview.build(project)
        os.environ["OTO_DB"] = _preview.database(project)
        os.environ["OTO_PROJECT_CONFIG"] = project.config_path
        os.environ.pop("OTO_STORE", None)
        import importlib
        from oto.serve import engine
        importlib.reload(engine)
        meta = _preview.read_meta(project)
        engine.MODE.update({"regime": "watch", "preview_built_at": meta["built_at"], "differs": meta["differs"], "rebuilds": 0})
        built = []
        watcher = _preview.Watcher(project, quiet=0.3, poll=0.1, on_built=lambda m: (built.append(m), engine.MODE.update(
            {"preview_built_at": m["built_at"], "differs": m["differs"], "rebuilds": engine.MODE["rebuilds"] + 1})), log=lambda *a: None).start()
        server = _http.Server(engine, "127.0.0.1", 0, project_root=root, identity=project.config()).start()
        try:
            status, _c, body = _get(server.url + "/api/status")
            assert json.loads(body)["mode"]["regime"] == "watch"
            status, _c, body = _get(server.url + "/api/changes")
            token = json.loads(body)["token"]
            status, _c, body = _get(server.url + "/api/changes?since=" + token)
            assert json.loads(body)["changed"] is False
            def resolved():
                _s, _c, body = _get(server.url + "/api/entity?term=system.billing")
                return (json.loads(body).get("data") or {}).get("resolved")
            assert resolved() != "system.billing", "not there yet"
            time.sleep(0.5)                                              # a full second after the preview was built
            _write(root, "proposals/memo.json", {"source_doc": "memo", "nodes": [NEW], "edges": []})
            for _ in range(60):
                if built:
                    break
                time.sleep(0.25)
            assert built, "the watcher rebuilt the preview after the proposal landed"
            for _ in range(20):
                if resolved() == "system.billing":
                    break
                time.sleep(0.25)
            assert resolved() == "system.billing", "the rebuilt preview is served with no restart"
            status, _c, body = _get(server.url + "/api/changes?since=" + token)
            assert json.loads(body)["changed"] is True and json.loads(body)["mode"]["rebuilds"] == 1
            status, _c, body = _get(server.url + "/api/pending")
            assert status == 200 and "Billing platform" in json.loads(body)["text"], "the tool has a GET route too"
            status, _c, body = _get(server.url + "/api/graph")
            payload = json.loads(body)
            assert payload["mode"]["regime"] == "watch" and payload["mode"]["differs"] == 1
            assert any(r["id"] == "system.billing" and r["station"] == "proposal" for r in payload["pending"])
            assert any(n["id"] == "system.billing" for n in payload["nodes"]), "in the preview store the fact is a node"
        finally:
            watcher.stop()
            server.stop()


def test_serve_preview_from_the_command_line_and_the_neo4j_flag_is_ignored():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _write(root, "proposals/memo.json", {"source_doc": "memo", "nodes": [NEW], "edges": []})
        env = dict(os.environ, PYTHONPATH=REPO)
        env.pop("OTO_STORE", None)
        r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root, "--preview", "entity", "system.billing"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=120) if False else None
        # `oto serve --http 0 --preview` builds the preview and binds; we only check it starts and reports
        proc = subprocess.Popen([sys.executable, "-m", "oto.cli", "serve", "--project", root, "--http", "0", "--preview", "--backend", "neo4j"],
                                cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.time() + 60
            lines = []
            while time.time() < deadline:
                line = proc.stderr.readline()
                if not line:
                    break
                lines.append(line)
                if "http: serving on" in line or "serving on" in line:
                    break
            text = "".join(lines)
            assert "preview built" in text and "ignored" in text, text
            assert os.path.exists(_preview.database(project))
        finally:
            proc.kill()
