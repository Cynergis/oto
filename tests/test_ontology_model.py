"""The ontology as a navigable model (roadmap D1): the vocabulary projected into classes with their
parents, children, relations with cardinality and attributes, so a person browses the ontology itself
and not only the instances. Served at /api/ontology, carried in the graph payload (and so in every
exported site), and shown on the workbench's Ontology page."""
import json
import os
import tempfile

from oto.apps import manifest as apps
from oto.builder import build
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init
from oto.serve import ontology as _ontology, payload as _payload

from test_apps import _engine, _get

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKBENCH = os.path.join(ROOT, "oto", "ui", "workbench")
SRC = os.path.join(ROOT, "ui-src", "workbench")


def _vocabulary(name):
    config, _s, _r = ontologies.load(name)
    return {"classes": config["classes"], "properties": config["properties"], "attributes": config.get("attributes") or {},
            "temporal": config.get("temporal") or {}, "ontology_version": config.get("ontology_version")}


def test_a_class_knows_its_parents_children_relations_and_attributes():
    m = _ontology.model(_vocabulary("software-architecture"))
    assert m["version"] is not None and m["derived_from_data"] is False
    by = {c["name"]: c for c in m["classes"]}
    assert [c["name"] for c in m["classes"]] == sorted(by), "classes in name order, one entry each"
    component = by["Component"]
    assert component["parents"] == ["Asset"] and "Asset" in component["ancestors"]
    assert "Component" in by["Asset"]["children"] and by["Asset"]["children"] == sorted(by["Asset"]["children"])
    assert component["label"] == "component" and component["definition"].startswith("A part of a system")
    assert "part_of" in component["requires"]
    part_of = next(r for r in component["relations_out"] if r["name"] == "part_of")
    assert part_of["cardinality"] == "0..1" and part_of["inverse"] == "contains" and "System" in part_of["to"], part_of
    assert part_of["inherited_from"] is None, "declared on Component itself"
    assert all(r["inherited_from"] is None for r in component["relations_out"]), "Asset declares no relation of its own in this pack"
    arch = {c["name"]: c for c in _ontology.model(_vocabulary("architecture"))["classes"]}
    nfr = arch["NFR"]
    assert nfr["parents"] == ["Requirement"] and nfr["label"] == "NFR", "an acronym stays as written"
    inherited = [r for r in nfr["relations_out"] if r["inherited_from"]]
    assert inherited and all(r["inherited_from"] == "Requirement" for r in inherited), "what Requirement declares, an NFR carries"
    assert any(r["name"] == "owned_by" for r in inherited)
    reached = next(r for r in nfr["relations_in"] if r["inherited_from"] == "Requirement"), "what reaches a Requirement reaches an NFR"
    system = by["System"]
    contains = next(r for r in system["relations_in"] if r["name"] == "part_of")
    assert "Component" in contains["from"] and contains["inverse"] == "contains"
    attrs = {a["name"]: a for a in by["Requirement"]["attributes"]}
    assert "kind" in attrs and attrs["kind"]["type"].startswith("enum:") and attrs["kind"]["values"], "a controlled attribute lists its values"
    rel = {r["name"]: r for r in m["relations"]}
    assert rel["part_of"]["cardinality"] == "0..1" and rel["part_of"]["domain"] and rel["part_of"]["range"] and rel["part_of"]["inverse"] == "contains"
    assert m["counts"]["classes"] == len(by) and m["counts"]["relations"] == len(rel) and m["counts"]["attributes"] == sum(len(c["attributes"]) for c in m["classes"])


def test_a_decision_attribute_and_a_required_one_are_marked():
    m = _ontology.model(_vocabulary("architecture"))
    by = {c["name"]: c for c in m["classes"]}
    status = next(a for a in by["Contract"]["attributes"] if a["name"] == "status")
    assert status["decision"] is True and status["default"] == "draft"
    m = _ontology.model(_vocabulary("architecture"))
    sha = next(a for a in {c["name"]: c for c in m["classes"]}["Commit"]["attributes"] if a["name"] == "sha")
    assert sha["required"] is True and sha["type"] == "string"


def test_one_class_or_an_unknown_one():
    m = _ontology.model(_vocabulary("software-architecture"))
    one = _ontology.for_class(m, "Component")
    assert one["name"] == "Component" and one["parents"] == ["Asset"]
    assert _ontology.for_class(m, "Nothing") is None


def test_a_vocabulary_derived_from_data_still_projects():
    nodes = [{"id": "a", "type": "Thing"}, {"id": "b", "type": "Other"}]
    edges = [{"from": "a", "rel": "near", "to": "b"}]
    m = _ontology.model(_payload.derived_vocabulary(nodes, edges))
    assert m["derived_from_data"] is True and m["version"] is None
    assert [c["name"] for c in m["classes"]] == ["Other", "Thing"]
    assert {r["name"] for r in m["relations"]} == {"near"} and m["relations"][0]["cardinality"] == "0..*" and m["relations"][0]["domain"] == []
    assert all(c["attributes"] == [] and c["parents"] == [] for c in m["classes"])


def test_counts_of_things_per_class_come_from_the_store():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="acme", name="Acme Platform", ontology="software-architecture")
        project = Project.standard(root)
        build(project)
        from oto.serve.store import SqliteStore
        store = SqliteStore(project.layout.database)
        try:
            payload = _payload.build(store, root, project.config(), passages=False)
        finally:
            store.close()
        m = payload["ontology"]
        by = {c["name"]: c for c in m["classes"]}
        assert by["Component"]["things"] == payload["counts"]["by_class"].get("Component", 0) > 0
        assert by["Asset"]["things"] == 0, "an abstract parent holds nothing of its own; its children do"
        assert m["relations"] and all("things" in r for r in m["relations"])


def test_served_at_api_ontology_and_in_the_payload():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="acme", name="Acme Platform", ontology="software-architecture")
        project = Project.standard(root)
        build(project)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("workbench", root), project_root=root, identity=project.config()).start()
        try:
            status, _c, text = _get(server.url + "/api/ontology")
            assert status == 200, text
            m = json.loads(text)
            assert {c["name"] for c in m["classes"]} >= {"System", "Component", "Asset"} and m["counts"]["classes"] > 5
            status, _c, text = _get(server.url + "/api/ontology?class=Component")
            assert status == 200 and json.loads(text)["parents"] == ["Asset"]
            status, _c, text = _get(server.url + "/api/ontology?class=Nothing")
            assert status == 404 and "Nothing" in text
            status, _c, text = _get(server.url + "/api/graph?passages=0")
            assert status == 200 and json.loads(text)["ontology"]["counts"]["classes"] == m["counts"]["classes"]
            status, _c, text = _get(server.url + "/api/tools")
            assert "/api/ontology" in text
        finally:
            server.stop()


def test_the_workbench_has_an_ontology_page():
    with open(os.path.join(WORKBENCH, "workbench.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert "#/ontology" in bundle and "Ontology" in bundle, "the tab and its route are in the built bundle"
    assert os.path.exists(os.path.join(SRC, "views", "Ontology.tsx"))
    with open(os.path.join(SRC, "App.tsx"), encoding="utf-8") as f:
        app = f.read()
    assert 'value="ontology"' in app and "Ontology" in app
    with open(os.path.join(SRC, "types.ts"), encoding="utf-8") as f:
        types = f.read()
    assert "ontology" in types and "OntologyModel" in types, "the payload type knows the model"
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "/api/ontology" in text
