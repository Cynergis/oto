"""The dependencies view (roadmap D4) and cross-artifact navigation (D5). The graph descriptors are
projected as a model: this graph and the graphs it depends on, who depends on whom, and the pairs an
agent could not tell apart flagged with the words that set them apart; served at /api/graphs and
carried in the payload. Any entity links to the rules that apply to its class, the terms and words
that name it, the graphs whose descriptor covers its class, the decisions about it and the
repository files behind it; served at /api/links and shown on the entity page."""
import json
import os
import tempfile

from oto.apps import manifest as apps
from oto.model import ontologies
from oto.serve import graphs as _graphs, lexicon as _lexicon, links as _links, rules as _rules

from test_apps import _engine, _get, _project

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKBENCH = os.path.join(ROOT, "oto", "ui", "workbench")
SRC = os.path.join(ROOT, "ui-src", "workbench")


def _descriptor(slug, label, subject, classes, reach=None):
    return {"id": "graph.%s" % slug, "type": "Graph", "label": label, "status": "current",
            "attributes": {"slug": slug, "subject": subject, "classes": classes, "reach": reach or "https://kg.example.org/" + slug}}


CLAIMS = ["Policy", "Coverage", "Claim", "Incident", "Document", "Tool", "Graph"]
GRAPHS = [
    _descriptor("acme", "Acme estate", "Acme estate: systems, components, interfaces and the risks to them.", ["System", "Component", "Interface", "Risk", "Document", "Tool", "Graph"]),
    _descriptor("policy", "Claims policy", "Claims policy: Motor vehicle claims: policy, coverage, claim, incident, handling.", CLAIMS),
    _descriptor("policy-2", "Claims policy, the copy", "Claims policy, the copy: Motor vehicle claims: policy, coverage, claim, incident, handling.", CLAIMS),
    dict(_descriptor("old", "The old estate", "The old estate, retired.", ["System"]), status="superseded"),
]
DEPENDS = [{"from": "graph.acme", "rel": "depends_on_graph", "to": "graph.policy", "status": "current"},
           {"from": "graph.acme", "rel": "depends_on_graph", "to": "graph.policy-2", "status": "current"}]


# ---- dependencies (D4) ----

def test_the_graphs_know_each_other_and_the_near_duplicates_are_flagged():
    m = _graphs.model(GRAPHS, DEPENDS, slug="acme")
    assert m["own"] == "graph.acme" and m["counts"] == {"graphs": 3, "dependencies": 2, "near_duplicates": 1}
    assert [g["id"] for g in m["graphs"]] == ["graph.acme", "graph.policy", "graph.policy-2"], "this graph first, then by id; a superseded descriptor is history"
    acme = m["graphs"][0]
    assert acme["own"] is True and acme["depends_on"] == ["graph.policy", "graph.policy-2"] and acme["depended_on_by"] == []
    assert acme["subject"].startswith("Acme estate") and acme["reach"] == "https://kg.example.org/acme" and "Component" in acme["classes"]
    assert acme["near_duplicates"] == []
    policy = m["graphs"][1]
    assert policy["own"] is False and policy["depended_on_by"] == ["graph.acme"] and policy["depends_on"] == []
    assert len(policy["near_duplicates"]) == 1
    near = policy["near_duplicates"][0]
    assert near["other"] == "graph.policy-2" and near["same_reach"] is False and near["similarity"] >= 0.75
    assert near["told_apart"] == {"this": [], "other": ["copy"]} and "told apart only by" in near["message"]
    assert m["graphs"][2]["near_duplicates"][0]["told_apart"] == {"this": ["copy"], "other": []}
    assert [(p["a"], p["b"]) for p in m["pairs"]] == [("graph.policy", "graph.policy-2")]
    assert _graphs.for_graph(m, "graph.policy")["id"] == "graph.policy" and _graphs.for_graph(m, "graph.nothing") is None


def test_a_graph_with_no_descriptor_and_one_whose_slug_is_not_its_own():
    assert _graphs.model([], [], slug="acme") == {"own": None, "counts": {"graphs": 0, "dependencies": 0, "near_duplicates": 0}, "graphs": [], "pairs": []}
    root = _descriptor("root", "Concierge", "Concierge: descriptors only.", ["Graph"])
    m = _graphs.model([root, GRAPHS[1]], [{"from": "graph.root", "rel": "depends_on_graph", "to": "graph.policy", "status": "current"}], slug=None)
    assert m["own"] == "graph.root", "with no slug, the one graph nothing depends on is this one"
    m = _graphs.model([GRAPHS[1], GRAPHS[2]], [], slug="acme")
    assert m["own"] is None and [g["id"] for g in m["graphs"]] == ["graph.policy", "graph.policy-2"], "two roots and no slug match: nobody is this graph"


# ---- links (D5) ----

def _vocabulary(name):
    config, _s, _r = ontologies.load(name)
    return {"classes": config["classes"], "properties": config["properties"], "attributes": config.get("attributes") or {},
            "schemes": config.get("schemes") or {}, "languages": config.get("languages") or ["en"]}


def _payload():
    vocabulary = _vocabulary("software-architecture")
    nodes = [
        {"id": "component.payment-api", "type": "Component", "label": "Payment API", "status": "current", "attributes": {},
         "source_doc": "arch-2026", "evidence": [{"doc": "arch-2026", "where": "section 3", "quote": "The payment API"}], "sources": ["arch-2026"]},
        {"id": "system.payments", "type": "System", "label": "Payments platform", "status": "current", "attributes": {}, "evidence": [], "sources": []},
        {"id": "repo.payment-api", "type": "Repository", "label": "acme/payment-api", "status": "current",
         "attributes": {"owner": "acme", "name": "payment-api", "url": "https://github.com/acme/payment-api", "default_branch": "main"}, "evidence": [], "sources": []},
        {"id": "decision.single-ledger", "type": "Decision", "label": "One ledger writer", "status": "current",
         "attributes": {"status": "accepted", "decided_on": "2026-01-15"}, "evidence": [], "sources": []},
        {"id": "decision.old", "type": "Decision", "label": "Two writers", "status": "superseded", "attributes": {}, "evidence": [], "sources": []},
        {"id": "document.arch-2026", "type": "Document", "label": "Architecture 2026", "status": "current", "attributes": {"kind": "spec"}, "evidence": [], "sources": []},
        {"id": "risk.outage", "type": "Risk", "label": "Ledger outage", "status": "current", "attributes": {}, "evidence": [], "sources": []},
    ] + GRAPHS[:2]
    edges = [
        {"from": "component.payment-api", "rel": "part_of", "to": "system.payments", "status": "current", "derived_by": None},
        {"from": "component.payment-api", "rel": "implemented_by", "to": "repo.payment-api", "status": "current", "derived_by": None},
        {"from": "decision.single-ledger", "rel": "governs", "to": "component.payment-api", "status": "current", "derived_by": None},
        {"from": "decision.old", "rel": "governs", "to": "component.payment-api", "status": "superseded", "derived_by": None},
        {"from": "component.payment-api", "rel": "documented_in", "to": "document.arch-2026", "status": "current", "derived_by": None},
        {"from": "risk.outage", "rel": "threatens", "to": "component.payment-api", "status": "current", "derived_by": None},
        DEPENDS[0],
    ]
    rules = list(ontologies.load_raw("software-architecture")["rules"]) + [
        {"id": "asset-has-an-owner", "kind": "policy", "severity": "warn", "when": [{"node": "a", "type": "Asset"}, {"not_edge": ["a", "owned_by", "*"]}],
         "then": {"flag": "an asset must have an owner"}, "why": "Nobody answers for it otherwise.", "validated_by": "Ada"}]
    rows = [{"phrase": "pay api", "canonical": "pay api", "target": "component.payment-api", "status": "current", "note": ""},
            {"phrase": "the platform", "canonical": "payments", "target": "system.payments", "status": "current", "note": ""}]
    return {"project": {"slug": "acme", "name": "Acme"}, "vocabulary": vocabulary, "nodes": nodes, "edges": edges,
            "rules": _rules.model(rules, vocabulary), "terms": _lexicon.model(vocabulary, rows, nodes),
            "graphs": _graphs.model(nodes, edges, slug="acme")}


def test_an_entity_links_to_its_rules_terms_graphs_decisions_and_files():
    links = _links.for_entity(_payload(), "component.payment-api")
    assert links["entity"] == "component.payment-api" and links["type"] == "Component"
    rules = {r["id"]: r for r in links["rules"]}
    assert rules["asset-has-an-owner"]["via"] == "Asset" and rules["risk-reaches-system"]["via"] is None
    assert rules["asset-has-an-owner"]["kind"] == "policy" and rules["asset-has-an-owner"]["severity"] == "warn"
    assert links["terms"] == [{"kind": "class", "name": "Component", "label": "component", "target": {"section": "ontology", "class": "Component"}},
                              {"kind": "phrase", "phrase": "pay api", "canonical": "pay api", "target": {"section": "lexicon", "query": "pay api"}}]
    assert links["graphs"] == [{"id": "graph.acme", "label": "Acme estate", "own": True, "reach": "https://kg.example.org/acme", "target": {"section": "dependencies", "graph": "graph.acme"}}], \
        "the policy graph's descriptor covers no Component"
    assert links["decisions"] == [{"id": "decision.single-ledger", "label": "One ledger writer", "rel": "governs", "direction": "in",
                                   "status": "accepted", "decided_on": "2026-01-15", "target": {"section": "knowledge", "entity": "decision.single-ledger"}}], \
        "a superseded decision is history"
    files = {f["kind"]: f for f in links["files"]}
    assert files["repository"] == {"id": "repo.payment-api", "label": "acme/payment-api", "kind": "repository", "where": "https://github.com/acme/payment-api",
                                   "rel": "implemented_by", "target": {"section": "knowledge", "entity": "repo.payment-api"}}
    assert files["document"]["id"] == "document.arch-2026" and files["document"]["rel"] == "documented_in"
    assert files["source"] == {"id": "document.arch-2026", "label": "Architecture 2026", "kind": "source", "where": "arch-2026 · section 3", "rel": None,
                               "target": {"section": "knowledge", "entity": "document.arch-2026"}}, "the evidence's document, found by its slug"
    assert [f["kind"] for f in links["files"]] == ["repository", "document", "source"]
    assert links["counts"] == {"rules": len(links["rules"]), "terms": 2, "graphs": 1, "decisions": 1, "files": 3}


def test_links_of_a_thing_nothing_points_at_and_of_a_decision_itself():
    payload = _payload()
    risk = _links.for_entity(payload, "risk.outage")
    assert risk["decisions"] == [] and risk["files"] == [] and risk["graphs"][0]["id"] == "graph.acme"
    assert [t["kind"] for t in risk["terms"]] == ["class"], "no phrase names it"
    decision = _links.for_entity(payload, "decision.single-ledger")
    assert decision["decisions"] == [], "a decision is not about itself"
    assert decision["graphs"] == [], "no descriptor covers Decision"
    assert _links.for_entity(payload, "nothing") is None
    bare = _links.for_entity({"project": {}, "vocabulary": {"classes": {"Thing": {}}, "properties": {}}, "nodes": [{"id": "t", "type": "Thing", "label": "T", "status": "current", "attributes": {}}],
                              "edges": [], "rules": None, "terms": None, "graphs": None}, "t")
    assert bare["rules"] == [] and bare["terms"] == [{"kind": "class", "name": "Thing", "label": "thing", "target": {"section": "ontology", "class": "Thing"}}]
    assert bare["graphs"] == [] and bare["files"] == []


# ---- served ----

def test_served_at_api_graphs_and_api_links_and_in_the_payload():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("workbench", root), project_root=root, identity=project.config()).start()
        try:
            status, _c, text = _get(server.url + "/api/graphs")
            assert status == 200, text
            m = json.loads(text)
            assert m["own"] == "graph.acme" and m["counts"]["graphs"] == 1 and m["graphs"][0]["own"] is True
            status, _c, text = _get(server.url + "/api/graphs?graph=graph.acme")
            assert status == 200 and json.loads(text)["id"] == "graph.acme"
            status, _c, text = _get(server.url + "/api/graphs?graph=graph.nothing")
            assert status == 404 and "graph.nothing" in text
            status, _c, text = _get(server.url + "/api/links?entity=component.payment-api")
            assert status == 200, text
            links = json.loads(text)
            assert "risk-reaches-system" in [r["id"] for r in links["rules"]] and links["graphs"][0]["id"] == "graph.acme"
            assert "repository" in [f["kind"] for f in links["files"]], "the sample's component is implemented by a repository"
            status, _c, text = _get(server.url + "/api/links?entity=nothing")
            assert status == 404 and "nothing" in text
            status, _c, text = _get(server.url + "/api/links")
            assert status == 400
            status, _c, text = _get(server.url + "/api/graph?passages=0")
            assert json.loads(text)["graphs"]["counts"] == m["counts"]
            status, _c, text = _get(server.url + "/api/tools")
            assert "/api/graphs" in text and "/api/links" in text
        finally:
            server.stop()


def test_the_workbench_has_a_dependencies_page_and_links_on_the_entity_page():
    with open(os.path.join(WORKBENCH, "workbench.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert "#/ontology/dependencies" in bundle, "the route is in the built bundle"
    assert os.path.exists(os.path.join(SRC, "views", "Dependencies.tsx")) and os.path.exists(os.path.join(SRC, "links.ts"))
    with open(os.path.join(SRC, "types.ts"), encoding="utf-8") as f:
        types = f.read()
    assert "GraphsModel" in types and "EntityLinks" in types
    with open(os.path.join(SRC, "views", "Knowledge.tsx"), encoding="utf-8") as f:
        knowledge = f.read()
    assert "links" in knowledge and "Related" in knowledge
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "/api/graphs" in text and "/api/links" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 26." in e2e and "/api/links" in e2e
