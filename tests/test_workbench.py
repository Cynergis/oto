"""The workbench: one app for a project, Overview, Knowledge (the reader's pages and the explorer's graph)
and Project (the stations). A built bundle in the package like the explorer's, read-only, served by
name with the snapshot beside the graph, and the reader and the explorer unchanged beside it."""
import json
import os
import tempfile

from oto.apps import manifest as apps
from oto.builder import build
from oto.project import Project
from oto.scaffold import init

from test_apps import _engine, _get

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKBENCH = os.path.join(ROOT, "oto", "ui", "workbench")


def test_the_workbench_is_a_valid_built_app_beside_the_others():
    from oto.model import ontologies
    vocabulary, _s, _r = ontologies.load("software-architecture")
    assert apps.problems(WORKBENCH, vocabulary) == []
    assert apps.resolve("workbench") == WORKBENCH
    assert apps.resolve("explorer").endswith("explorer") and apps.resolve("reader").endswith("reader"), "both kept"
    for name in ("index.html", "workbench.js", "workbench.css", "app.json"):
        assert os.path.exists(os.path.join(WORKBENCH, name)), name
    with open(os.path.join(WORKBENCH, "workbench.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert len(bundle) > 100000, "a built bundle: React, shadcn's components and the explorer's graph inside"
    assert "cdn" not in bundle.lower() and "fonts.googleapis" not in bundle, "no runtime network"
    for route in ("api/status", "api/changes", "data.json", "snapshot.json"):
        assert route in bundle, route
    assert "#/work" in bundle and "waits on" in bundle, "the Work page: the board over the snapshot's work section"
    with open(os.path.join(WORKBENCH, "workbench.css"), encoding="utf-8") as f:
        css = f.read()
    assert "--mx-accent" in css and "--primary" in css, "the explorer's variables renamed beside shadcn's tokens"
    assert "fonts.googleapis" not in css


def test_served_by_name_with_the_snapshot_beside_the_graph():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="acme", name="Acme Platform", ontology="software-architecture")
        project = Project.standard(root)
        build(project)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("workbench", root), project_root=root,
                              identity=project.config()).start()
        try:
            status, _c, html = _get(server.url + "/")
            assert status == 200 and "workbench.js" in html and 'id="workbench"' in html
            status, ctype, _t = _get(server.url + "/workbench.js")
            assert status == 200 and "javascript" in ctype
            status, _c, text = _get(server.url + "/api/status")
            snap = json.loads(text)["snapshot"]
            assert snap["project"]["name"] == "Acme Platform" and len(snap["stations"]) == 8
            status, _c, text = _get(server.url + "/data.json")
            assert status == 200 and json.loads(text)["nodes"]
        finally:
            server.stop()
