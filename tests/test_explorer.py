"""The graph explorer: the generic default app. Its pure modules under Node over a real payload,
the built bundle in the package, served and exported by default, a project's explorer.json
override served and copied, and the reader still there by name."""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

from oto.apps import manifest as apps
from oto.builder import build
from oto.cli import main
from oto.project import Project
from oto.scaffold import init
from oto.serve import payload as _payload
from oto.serve.store import SqliteStore

from test_apps import _engine, _get

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXPLORER = os.path.join(ROOT, "oto", "ui", "explorer")
SRC = os.path.join(ROOT, "ui-src", "explorer")
NODE = shutil.which("node")


def _project(root):
    init(root, slug="acme", name="Acme Platform", ontology="software-architecture")
    project = Project.standard(root)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    graph["nodes"].append({"id": "system.old", "type": "System", "label": "Old platform", "aliases": [], "summary": "retired",
                           "attributes": {}, "tags": [], "as_of": "2025-01-01", "valid_from": "2025-01-01", "valid_to": "2026-01-01",
                           "source_doc": "sample", "status": "superseded", "superseded_by": "system.payments", "sources": ["sample"]})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    build(project)
    return project


def test_the_explorer_is_a_valid_built_app_and_the_default():
    from oto.model import ontologies
    vocabulary, _s, _r = ontologies.load("software-architecture")
    assert apps.problems(EXPLORER, vocabulary) == []
    manifest = apps.read(EXPLORER)
    assert manifest["overrides"] == ["explorer.json"] and manifest["data"][0]["root"] == {"$graph": True}
    assert apps.resolve("explorer") == EXPLORER and apps.resolve("reader").endswith("reader")
    for name in ("index.html", "explorer.js", "explorer.css", "app.json"):
        assert os.path.exists(os.path.join(EXPLORER, name)), name
    with open(os.path.join(EXPLORER, "explorer.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert len(bundle) > 100000 and "http" not in bundle[:200], "a built bundle, React and React Flow inside"
    assert "cdn" not in bundle.lower()[:5000]


@pytest.mark.skipif(not NODE, reason="node is not on the PATH")
def test_the_adapter_and_the_defaults_under_node():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        store = SqliteStore(project.layout.database)
        try:
            payload = _payload.build(store, root, project.config())
        finally:
            store.close()
        path = os.path.join(root, "payload.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        r = subprocess.run([NODE, os.path.join(HERE, "explorer_checks.js"), SRC, path], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["historyNodes"] == out["nodes"] + 1, "a superseded node is dropped unless history is asked for"
        assert out["inverses"]["owned_by"] == "owns" and out["inverses"]["part_of"] == "contains"
        assert out["edgeSample"]["dash"] is True and out["edgeSample"]["derived_by"] == "risk-reaches-system" and out["edgeSample"]["premises"]
        assert ["datastore.ledger", "contains", "in"] in out["neighbours"], "an incoming edge reads by its inverse"
        assert ["team.payments", "owned by", "out"] in out["neighbours"], "an edge reads as the vocabulary labels it"
        assert "datastore.ledger" in out["hop1"] and "system.payments" in out["hop1"] and out["hop2"] > len(out["hop1"])
        assert out["sub"] == ["part_of"]
        lane = out["lane"]
        assert lane["nodes"] == 1 and lane["edges"] == 1 and lane["pending"] == 5 and lane["refused"] == 2
        assert lane["billing"]["station"] == "proposal" and lane["billing"]["verdict"] == "new" and lane["ghost"] is False
        assert lane["marked"] == "candidate" and lane["markedInList"] == "changed", "an existing entity the candidate changes is marked, in the index and the list"
        assert lane["edge"] == [["system.billing", "owned_by", "team.payments", "proposal"]] and lane["off"] == 0
        assert out["search"][0] in ("datastore.ledger", "decision.single-ledger")
        assert out["assumed"] == 0, "every sample entity cites its sample source"
        assert out["assumedStripped"] is True and out["assumedDocument"] is False, "a document is never unsourced; an entity with no source is"
        assert out["columns"][0] == ["Document"] and sum(len(c) for c in out["columns"]) == 15 and len(out["columns"]) <= 9
        assert "Document" not in out["evidenceable"] and "System" in out["evidenceable"] and out["threshold"] == 400
        assert out["meta"]["DecisionRecord"] == ["Decision Record", "check", True] and out["meta"]["Risk"][1] == "warn"
        assert out["overColumns"][:2] == [["Risk"], ["System", "Component"]] and len(out["overColumns"]) == 3, "forgotten classes still get a column"
        assert out["overRisk"]["colour"] == "red" and out["overEvidenceable"] == ["Risk"] and out["overThreshold"] == 5 and out["overTitle"] == "Custom"
        assert out["icons"] == ["doc", "check", "warn", "user", "metric", "journey", "graph", "policy", "usecase", "usecase"]
        assert out["readable"] == ["Decision Record", "data store"]


def test_served_by_default_with_a_project_override_and_exported():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        os.makedirs(os.path.join(root, "views"), exist_ok=True)
        with open(os.path.join(root, "views", "explorer.json"), "w", encoding="utf-8") as f:
            json.dump({"columns": [["Team"], ["System"]], "title": "Acme graph"}, f)
        engine = _engine(project)
        app = apps.resolve(None) or apps.resolve("explorer", root)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=app, project_root=root, identity=project.config()).start()
        try:
            status, ctype, html = _get(server.url + "/")
            assert status == 200 and "explorer.js" in html
            status, ctype, text = _get(server.url + "/explorer.js")
            assert status == 200 and "javascript" in ctype
            status, ctype, text = _get(server.url + "/explorer.json")
            assert status == 200 and json.loads(text)["title"] == "Acme graph", "the project's override is served beside the app"
            status, _c, text = _get(server.url + "/data.json")
            assert json.loads(text)["vocabulary"]["classes"]["System"]
        finally:
            server.stop()
        assert main(["build", "--project", root, "--target", "site"]) == 0
        site = project.layout.site
        for name in ("index.html", "explorer.js", "explorer.css", "data.json", "explorer.json"):
            assert os.path.exists(os.path.join(site, name)), name
        with open(os.path.join(site, "explorer.json"), encoding="utf-8") as f:
            assert json.load(f)["title"] == "Acme graph"
        # without an override nothing is served for it, and the app still works
        os.remove(os.path.join(root, "views", "explorer.json"))
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("explorer", root), project_root=root, identity=project.config()).start()
        try:
            status, _c, _t = _get(server.url + "/explorer.json")
            assert status == 404
        finally:
            server.stop()


def test_a_pack_may_supply_the_override(monkeypatch, capsys):
    from oto.model import packs
    with tempfile.TemporaryDirectory() as home:
        monkeypatch.setenv(packs.USER_DIR_ENV, os.path.join(home, "packs"))
        assert main(["pack", "new", "arch-tuned", "--ontology", "software-architecture"]) == 0
        base = packs.dir_for("arch-tuned")
        os.makedirs(os.path.join(base, "views"))
        with open(os.path.join(base, "views", "explorer.json"), "w", encoding="utf-8") as f:
            json.dump({"threshold": 50}, f)
        assert packs.check(base) == [], "an override file beside no app is fine"
        with tempfile.TemporaryDirectory() as root:
            init(root, slug="t", name="T", ontology="software-architecture")
            manifest = apps.read(EXPLORER)
            found = apps.override_files(manifest, root)
            assert found["explorer.json"] == os.path.join(base, "views", "explorer.json")
