"""The generic reader: its pages under Node over a real payload, and the app served live and
exported static as the default."""
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

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(os.path.dirname(HERE), "oto", "ui", "reader")
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
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)
    with open(os.path.join(root, "notes", "ledger.md"), "w", encoding="utf-8") as f:
        f.write("# The ledger note\n\nThe payments ledger records every transfer.\n")
    build(project)
    return project


def test_the_reader_is_a_valid_app_on_the_contract():
    from oto.model import ontologies
    vocabulary, _s, _r = ontologies.load("software-architecture")
    assert apps.problems(READER, vocabulary) == []
    assert apps.resolve("reader") == READER
    assert ("reader", READER, "built-in") in apps.available()


@pytest.mark.skipif(not NODE, reason="node is not on the PATH")
def test_the_pages_render_the_graph_under_node():
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
        r = subprocess.run([NODE, os.path.join(HERE, "reader_checks.js"), os.path.join(READER, "reader.js"), path],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert "System" in out["classes"] and "Document" in out["classes"]
        assert out["routes"]["#/search?q=payments+ledger"] == {"page": "search", "arg": "", "params": {"q": "payments ledger"}}
        assert out["routes"]["#/entity/system.payments"]["arg"] == "system.payments"
        home = out["pages"]["#/"]
        assert "Acme Platform" in home and "derived by rules" in home and "#/type/System" in home and "Most connected" in home
        section = out["pages"]["#/type/System"]
        assert "Payments platform" in section and "Old platform" in section and 'class="badge superseded"' in section
        card = out["pages"]["#/entity/system.payments"]
        for expected in ("Payments platform", "status=current", "as_of=", "Referenced by", "part_of", "Ledger database",
                         "derived by risk-reaches-system", "rests on", "History", "Old platform", "Sources", "#/doc/sample"):
            assert expected in card, expected
        assert "<script" not in card
        doc = out["pages"]["#/doc/handbook"]
        assert "Operations handbook" in doc and "Cited by" in doc and "Bulletin 2026-01" in doc, "the bulletin cites the handbook"
        note = out["pages"]["#/doc/notes/ledger"]
        assert "The ledger note" in note and "records every transfer" in note and out["passage"] == "The ledger note"
        srch = out["pages"]["#/search?q=payments+ledger"]
        assert "Ledger database" in srch and "notes/ledger.md" in srch
        assert "datastore.ledger" in out["search"]["ledger"]["entities"][:3] and "notes/ledger.md" in out["search"]["ledger"]["passages"]
        assert out["search"]["empty"] == {"entities": [], "passages": []} and out["search"]["nothing"]["entities"] == []
        findings = out["pages"]["#/findings"]
        assert "decision-is-documented" in findings and "risk-reaches-system" in findings
        assert "Nothing recorded in the ledger" in out["pages"]["#/changes"]
        assert "Documents" in out["pages"]["#/docs"] and "No such page" in out["pages"]["#/nope"]
        assert "Not in the graph" in out["pages"]["#/entity/missing.id"]
        assert 'class="active"' in out["side"] and "Findings and rules" in out["side"]


def test_the_reader_serves_and_exports_by_name():
    import urllib.request
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        import importlib
        os.environ["OTO_DB"] = project.layout.database
        os.environ["OTO_PROJECT_CONFIG"] = project.config_path
        os.environ.pop("OTO_STORE", None)
        from oto.serve import engine
        importlib.reload(engine)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("reader"), project_root=root, identity=project.config()).start()
        try:
            with urllib.request.urlopen(server.url + "/", timeout=10) as r:
                html = r.read().decode("utf-8")
            assert "<title>OTO reader</title>" in html and "reader.js" in html
            with urllib.request.urlopen(server.url + "/reader.css", timeout=10) as r:
                assert r.headers.get("Content-Type", "").startswith("text/css")
            with urllib.request.urlopen(server.url + "/data.json", timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            assert data["project"]["name"] == "Acme Platform" and data["nodes"]
        finally:
            server.stop()
        assert main(["build", "--project", root, "--target", "site", "--view", "reader"]) == 0
        site = project.layout.site
        for name in ("index.html", "reader.js", "reader.css", "app.json", "data.json"):
            assert os.path.exists(os.path.join(site, name)), name
        with open(os.path.join(site, "data.json"), encoding="utf-8") as f:
            assert json.load(f)["nodes"], "the app's data.json is the payload"
