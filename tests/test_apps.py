"""Views: the projection language on a fixture payload, the manifest and its checks,
the data files in each format, three differently shaped fixture apps served live and exported
static, and views resolved by name."""
import json
import os
import shutil
import tempfile

import pytest

from oto.apps import manifest as apps, projection as proj
from oto.builder import build
from oto.cli import main
from oto.project import Project, ProjectError
from oto.scaffold import init
from oto.serve import payload as _payload
from oto.serve.store import SqliteStore

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "apps")


def _n(nid, kind, label, status="current", **attrs):
    return {"id": nid, "type": kind, "label": label, "status": status, "summary": "about " + label,
            "as_of": "2026-01-01", "valid_from": "2026-01-01", "valid_to": None, "source_doc": "doc",
            "sources": ["doc"], "tags": [], "aliases": [], "evidence": [{"doc": "doc", "where": "p1", "quote": "q"}],
            "degree": 0, "attributes": attrs}


PAYLOAD = {
    "nodes": [_n("sys.a", "System", "Alpha", tier="1"), _n("sys.b", "System", "Beta", tier="2"),
              _n("sys.old", "System", "Old", status="superseded", tier="9"),
              _n("dec.1", "DecisionRecord", "Use one ledger", status="current", reason="consistency", decided_on="2026-02-01"),
              _n("dec.2", "DecisionRecord", "Adopt queues", reason="decoupling", decided_on="2026-03-01"),
              _n("risk.1", "Risk", "Single point")],
    "edges": [{"from": "sys.a", "rel": "decided_by", "to": "dec.1", "status": "current", "derived_by": None, "premises": []},
              {"from": "sys.b", "rel": "decided_by", "to": "dec.1", "status": "current", "derived_by": None, "premises": []},
              {"from": "sys.old", "rel": "decided_by", "to": "dec.2", "status": "current", "derived_by": None, "premises": []},
              {"from": "risk.1", "rel": "threatens", "to": "sys.a", "status": "current", "derived_by": None, "premises": []},
              {"from": "risk.1", "rel": "threatens", "to": "sys.b", "status": "derived", "derived_by": "r1", "premises": ["x"]},
              {"from": "sys.a", "rel": "part_of", "to": "sys.b", "status": "superseded", "derived_by": None, "premises": []}],
    "lexicon": [{"phrase": "alpha", "canonical": "Alpha", "target": "sys.a", "status": "current", "note": ""},
                {"phrase": "the alpha", "canonical": "Alpha", "target": "sys.a", "status": "current", "note": ""},
                {"phrase": "mill", "canonical": "The mill", "target": "", "status": "not_ingested", "note": "no doc"}],
    "documents": [{"id": "doc.x", "label": "Doc X", "as_of": "2026-01-01", "valid_from": None, "attributes": {}}],
    "findings": [{"rule": "p1", "severity": "warn", "node": "sys.a", "message": "m"}],
    "ledger": [{"at": "2026-03-01", "by": "me", "note": "n"}, {"at": "2026-02-01", "by": "me", "note": "o"}],
    "vocabulary": {"classes": {"System": {"definition": ""}, "DecisionRecord": {"definition": ""}, "Risk": {"definition": ""}},
                   "properties": {"decided_by": [], "threatens": [], "part_of": []}, "attributes": {}},
}


def P(expr, **kw):
    return proj.project(expr, PAYLOAD, **kw)


# ---- the language ----

def test_nodes_where_sort_limit_history_and_shapes():
    assert [n["id"] for n in P({"$nodes": "System"})] == ["sys.a", "sys.b"], "superseded excluded"
    assert [n["id"] for n in P({"$nodes": "System", "$history": True})] == ["sys.a", "sys.b", "sys.old"]
    assert P({"$nodes": "System", "$field": "$label", "$sort": "-attr.tier"}) == ["Beta", "Alpha"]
    assert P({"$nodes": ["System", "Risk"], "$map": "$id", "$sort": "label", "$limit": 2}) == ["sys.a", "sys.b"]
    assert P({"$nodes": "DecisionRecord", "$where": {"attr.reason": "consistency"}, "$map": "$id"}) == ["dec.1"]
    assert P({"$nodes": "DecisionRecord", "$where": {"attr.decided_on": {"$in": ["2026-03-01"]}}, "$map": "$id"}) == ["dec.2"]
    assert P({"$nodes": "System", "$where": {"attr.tier": {"$ne": "1"}}, "$map": "$id"}) == ["sys.b"]
    assert P({"$nodes": "*", "$where": {"attr.reason": {"$exists": True}}, "$map": "$id"}) == ["dec.1", "dec.2"]
    assert P({"$nodes": "*", "$where": {"label": {"$contains": "queue"}}, "$map": "$id"}) == ["dec.2"]
    grouped = P({"$nodes": "*", "$history": True, "$group": "type", "$map": "$id"})
    assert [g["key"] for g in grouped] == ["DecisionRecord", "Risk", "System"] and grouped[2]["items"] == ["sys.a", "sys.b", "sys.old"]
    mapped = P({"$nodes": "DecisionRecord", "$map": {"id": "$id", "why": "$attr.reason", "all": "$attrs", "row": "$row",
                                                     "title": {"$format": "{label} on {attr.decided_on}"}, "n": 1, "lit": "plain"}})
    assert mapped[0] == {"id": "dec.1", "why": "consistency", "all": {"reason": "consistency", "decided_on": "2026-02-01"},
                         "row": PAYLOAD["nodes"][3], "title": "Use one ledger on 2026-02-01", "n": 1, "lit": "plain"}


def test_out_and_in_follow_edges_with_select_derived_and_history():
    dec = {"$nodes": "DecisionRecord", "$sort": "id", "$map": {"id": "$id", "affects": {"$in": "decided_by", "$select": "$id"}}}
    assert P(dec) == [{"id": "dec.1", "affects": ["sys.a", "sys.b"]}, {"id": "dec.2", "affects": []}], "a superseded source is dropped"
    assert P({"$nodes": "DecisionRecord", "$map": {"$in": "decided_by", "$history": True}})[1] == ["sys.old"]
    risk = {"$nodes": "Risk", "$map": {"$out": "threatens", "$select": {"id": "$id", "via": "$rel", "status": "$edge_status"}, "$derived": "mark"}}
    assert P(risk)[0] == [{"id": "sys.a", "via": "threatens", "status": "current", "derived_by": None},
                          {"id": "sys.b", "via": "threatens", "status": "derived", "derived_by": "r1"}]
    assert P({"$nodes": "Risk", "$map": {"$out": "threatens", "$derived": "exclude"}})[0] == ["sys.a"]
    assert P({"$nodes": "Risk", "$map": {"$out": "threatens", "$select": "$label", "$derived": "mark"}})[0][1] == {"value": "Beta", "derived_by": "r1"}
    assert P({"$nodes": "System", "$map": {"$out": "part_of"}}) == [[], []], "a superseded edge is dropped"
    assert P({"$nodes": "System", "$map": {"$out": "part_of", "$history": True}})[0] == ["sys.b"]
    assert P({"$nodes": "Risk", "$map": {"$out": "*", "$sort": "-label", "$limit": 1}})[0] == ["sys.b"]
    assert P({"$nodes": "Risk", "$map": {"$out": "threatens", "$where": {"attr.tier": "1"}}})[0] == ["sys.a"]


def test_reductions_literals_and_the_other_parts_of_the_payload():
    assert P({"$first": {"$nodes": "System", "$field": "$summary"}}) == "about Alpha"
    assert P({"$first": {"$nodes": "Nope"}}) is None
    assert P({"$count": {"$nodes": "DecisionRecord"}}) == 2 and P({"$count": {"$const": "x"}}) == 1
    assert P({"$const": "$not-a-path"}) == "$not-a-path"
    assert P({"$nodes": "System", "$limit": 1, "$map": {"$concat": ["$label", " / ", "$attr.tier"]}}) == ["Alpha / 1"]
    lex = P({"$lexicon": True, "$map": {"term": "$term", "phrases": "$phrases", "targets": "$targets"}})
    assert lex == [{"term": "Alpha", "phrases": ["alpha", "the alpha"], "targets": ["sys.a"]},
                   {"term": "The mill", "phrases": ["mill"], "targets": []}]
    assert P({"$documents": True, "$map": "$label"}) == ["Doc X"]
    assert P({"$findings": True, "$map": "$rule"}) == ["p1"]
    assert P({"$ledger": True, "$limit": 1, "$map": "$at"}) == ["2026-03-01"]
    assert len(P({"$edges": True, "$where": {"status": "derived"}})) == 1
    assert P({"$pending": True}) == []


def test_include_and_errors(tmp_path):
    with open(os.path.join(tmp_path, "part.json"), "w", encoding="utf-8") as f:
        json.dump({"$nodes": "Risk", "$map": "$id"}, f)
    assert P({"$include": "part.json"}, base_dir=str(tmp_path)) == ["risk.1"]
    with pytest.raises(proj.ProjectionError, match="leaves the app directory"):
        P({"$include": "../etc/passwd"}, base_dir=str(tmp_path))
    with pytest.raises(proj.ProjectionError, match="no such file"):
        P({"$include": "missing.json"}, base_dir=str(tmp_path))
    with pytest.raises(proj.ProjectionError, match="needs the app directory"):
        P({"$include": "part.json"})
    with pytest.raises(proj.ProjectionError, match="unknown operator \\$frobnicate"):
        P({"$frobnicate": 1})
    with pytest.raises(proj.ProjectionError, match="outside a row"):
        P("$label")
    with pytest.raises(proj.ProjectionError, match="outside a row"):
        P({"$out": "threatens"})


def test_references_collect_what_a_projection_names(tmp_path):
    refs = proj.references({"a": {"$nodes": ["System", "Risk"], "$sort": "-attr.tier", "$where": {"attr.reason": "x"},
                                  "$map": {"x": {"$in": "decided_by", "$select": "$attr.status"}, "t": {"$format": "{attr.decided_on}"}}},
                            "b": {"$include": "part.json"}}, base_dir=str(tmp_path))
    assert refs["classes"] == {"System", "Risk"} and refs["relations"] == {"decided_by"}
    assert refs["attributes"] == {"tier", "reason", "status", "decided_on"} and refs["includes"] == ["part.json"]


# ---- the manifest ----

def test_fixture_apps_are_valid_against_the_architecture_vocabulary():
    from oto.model import ontologies
    vocabulary, _sample, _readme = ontologies.load("software-architecture")
    for name in ("globals-site", "json-pages", "live-only"):
        assert apps.problems(os.path.join(FIXTURES, name), vocabulary) == [], name
    m = apps.read(os.path.join(FIXTURES, "live-only"))
    assert m["data"] == [] and m["_declared"] and m["requires"] == {"classes": ["System"]}
    assert apps.read(os.path.join(FIXTURES, "globals-site"))["adapter"] == "adapter.js"


def test_manifest_problems_are_named(tmp_path):
    app = tmp_path / "bad"
    app.mkdir()
    (app / "app.json").write_text(json.dumps({
        "name": "Bad App", "entry": "main.html", "engine": "~1", "adapter": "nope.js",
        "data": [{"format": "json"}, {"file": "a.js", "format": "yaml"}, {"file": "b.js", "format": "js-globals"},
                 {"file": "c.json", "format": "json"}, {"file": "../d.json", "format": "json", "root": {"$nodes": "Ghost", "$map": {"$out": "haunts"}}},
                 {"file": "e.json", "format": "json", "root": {"$include": "gone.json"}}],
        "requires": {"classes": ["Nope"], "relations": ["never"], "attributes": {"System": ["colour"]}}}), encoding="utf-8")
    vocabulary = {"classes": {"System": {"definition": ""}}, "properties": {"part_of": []}, "attributes": {"System": {"tier": {"type": "string", "definition": ""}}}}
    text = "\n".join(apps.problems(str(app), vocabulary))
    for expected in ("must be lowercase", "entry 'main.html' is not", "not a spec", "adapter 'nope.js'", "entry 1 needs a `file`",
                     "format 'yaml'", "needs `globals`", "needs `root` or `globals`", "relative path inside the app",
                     "$include 'gone.json'", "names class 'Ghost'", "names relation 'haunts'",
                     "requires class 'Nope'", "requires relation 'never'", "requires attribute System.colour"):
        assert expected in text, (expected, text)
    with pytest.raises(apps.AppError, match="cannot be served"):
        apps.check_requires(apps.read(str(app)), vocabulary)
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "index.html").write_text("<title>x</title>", encoding="utf-8")
    assert apps.problems(str(plain), vocabulary) == [] and apps.read(str(plain))["_declared"] is False


def test_render_each_format():
    entry = {"file": "x", "format": "js-globals", "globals": {"__A__": {"$count": {"$nodes": "System"}}, "__B__": {"$const": [1]}}}
    assert apps.render(entry, PAYLOAD, None).splitlines()[1:] == ["window.__A__ = 2;", "window.__B__ = [1];"]
    entry = {"file": "x", "format": "js-module", "globals": {"a": {"$const": {"k": "v"}}}}
    assert "export const a = {\"k\":\"v\"};" in apps.render(entry, PAYLOAD, None)
    entry = {"file": "x", "format": "json", "root": {"$nodes": "Risk", "$map": "$id"}}
    assert json.loads(apps.render(entry, PAYLOAD, None)) == ["risk.1"]
    entry = {"file": "x", "format": "json", "globals": {"n": {"$count": {"$nodes": "*"}}}}
    assert json.loads(apps.render(entry, PAYLOAD, None)) == {"n": 5}


def test_resolve_by_path_and_by_name(tmp_path):
    assert apps.resolve(None) is None
    assert apps.resolve(os.path.join(FIXTURES, "live-only")) == os.path.join(FIXTURES, "live-only")
    with pytest.raises(apps.AppError, match="is not a directory"):
        apps.resolve("/nowhere/at/all")
    project = tmp_path / "p"
    shutil.copytree(os.path.join(FIXTURES, "json-pages"), str(project / "views" / "json-pages"))
    assert apps.resolve("json-pages", str(project)) == str(project / "views" / "json-pages")
    with pytest.raises(apps.AppError, match="no view named 'ghost'"):
        apps.resolve("ghost", str(project))
    assert [(n, w) for n, _d, w in apps.available(str(project))][:1] == [("json-pages", "project")]


# ---- served live and exported static ----

def _project(root):
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    project = Project.standard(root)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "payments", "aka": ["the platform"], "targets": ["system.payments"], "status": "current", "note": ""}]}, f)
    build(project)
    return project


def _engine(project):
    import importlib
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine
    importlib.reload(engine)
    return engine


def _get(url):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read().decode("utf-8")


def test_the_three_fixture_apps_served_live_and_exported_static():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        expected_dir = os.path.join(FIXTURES, "expected")
        for name in ("globals-site", "json-pages", "live-only"):
            app = os.path.join(FIXTURES, name)
            server = _http.Server(engine, "127.0.0.1", 0, app_dir=app, project_root=root, identity=project.config()).start()
            try:
                status, ctype, body = _get(server.url + "/")
                assert status == 200 and "<title>" in body, name
                status, _c, body = _get(server.url + "/api/status")
                assert json.loads(body)["app"]["name"] == name
                live = {}
                for rel in json.loads(body)["app"]["data"]:
                    status, ctype, text = _get(server.url + "/" + rel)
                    assert status == 200, (name, rel, text)
                    assert ("json" in ctype) == rel.endswith(".json")
                    live[rel] = text
            finally:
                server.stop()
            # the static export writes the same files, byte for byte, and the checked-in expectation holds
            if name == "live-only":
                project.options = {"targets": {"site"}, "verify": False, "view": app}
                with pytest.raises(ProjectError, match="declares no data files"):
                    build(project)
                continue
            project.options = {"targets": {"site"}, "verify": False, "view": app}
            build(project)
            for rel, text in live.items():
                with open(os.path.join(project.layout.site, rel), encoding="utf-8") as f:
                    assert f.read() == text, (name, rel)
                with open(os.path.join(expected_dir, name, rel), encoding="utf-8") as f:
                    assert f.read() == text, "expected output for %s/%s changed; review and update the fixture" % (name, rel)
            assert os.path.exists(os.path.join(project.layout.site, "index.html"))
        # what the globals site got
        data = live if False else None
        with open(os.path.join(project.layout.site, "data", "systems.json"), encoding="utf-8") as f:
            systems = json.load(f)
        assert systems[0]["id"] == "system.payments" and any(p["id"] == "datastore.ledger" for p in systems[0]["parts"])


def test_an_app_the_vocabulary_cannot_feed_is_refused_live_and_static(tmp_path):
    from oto.serve import http as _http
    app = tmp_path / "needy"
    app.mkdir()
    (app / "index.html").write_text("<title>needy</title>", encoding="utf-8")
    (app / "app.json").write_text(json.dumps({"name": "needy", "entry": "index.html",
                                              "data": [{"file": "d.js", "format": "js-globals", "globals": {"X": {"$const": 1}}}],
                                              "requires": {"classes": ["Ghost"]}}), encoding="utf-8")
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=str(app), project_root=root, identity=project.config()).start()
        try:
            status, _c, text = _get(server.url + "/d.js")
            assert status == 500 and "requires class 'Ghost'" in text
        finally:
            server.stop()
        assert main(["build", "--project", root, "--target", "site", "--view", str(app)]) == 1
        (app / "app.json").write_text("not json", encoding="utf-8")
        import subprocess, sys
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root, "--http", "0", "--view", str(app)],
                           cwd=repo, env=dict(os.environ, PYTHONPATH=repo), capture_output=True, text=True, timeout=60)
        assert r.returncode == 1 and "not usable" in r.stderr
