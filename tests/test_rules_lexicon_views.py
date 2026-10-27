"""The rules view (roadmap D2) and the lexicon view (D3). The rules are projected as what each one
touches, in words, and looked up by class with inheritance, served at /api/rules; the vocabulary's
terms in every declared language and the words people use are searchable, each hit landing on the
element it names, served at /api/lexicon. Both ride in the graph payload (and so in every exported
site) and show on the workbench's Ontology tab."""
import json
import os
import tempfile

from oto.apps import manifest as apps
from oto.model import ontologies
from oto.serve import lexicon as _lexicon, rules as _rules

from test_apps import _engine, _get, _project

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKBENCH = os.path.join(ROOT, "oto", "ui", "workbench")
SRC = os.path.join(ROOT, "ui-src", "workbench")


def _vocabulary(name):
    config, _s, _r = ontologies.load(name)
    return {"classes": config["classes"], "properties": config["properties"], "attributes": config.get("attributes") or {},
            "schemes": config.get("schemes") or {}, "languages": config.get("languages") or ["en"]}


def _roadmap():
    with open(os.path.join(ROOT, "roadmap", "ontology.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    with open(os.path.join(ROOT, "roadmap", "rules.json"), encoding="utf-8") as f:
        rules = json.load(f)["rules"]
    return rules, {"classes": config["classes"], "properties": config["properties"], "attributes": config.get("attributes") or {},
                   "schemes": config.get("schemes") or {}, "languages": config.get("languages") or ["en"]}


# ---- rules (D2) ----

def test_a_rule_reads_as_what_it_touches_and_why():
    rules, vocabulary = _roadmap()
    m = _rules.model(rules, vocabulary)
    assert m["counts"]["rules"] == len(rules) == m["counts"]["policy"] + m["counts"]["derive"]
    assert [r["id"] for r in m["rules"]] == [r["id"] for r in rules], "declaration order, every rule once"
    by = {r["id"]: r for r in m["rules"]}
    cap = by["needed-capability-has-a-provider"]
    assert cap["kind"] == "policy" and cap["severity"] == "warn" and cap["answers"] == "PF4"
    assert cap["when"] == ["c is a Capability where state = needed", "no edge * provides c"]
    assert cap["then"] == "flag: a capability the portfolio needs has no product providing it"
    assert cap["classes"] == ["Capability"] and cap["relations"] == ["provides"] and cap["attributes"] == ["Capability.state"]
    assert cap["every_node"] is False and cap["validated_by"] is None and cap["why"].startswith("The gap")
    state = by["state-follows-the-current-transition"]
    assert state["kind"] == "derive" and state["severity"] is None
    assert state["when"] == ["t is a Transition", "edge t transition_of w"] and state["then"] == "set w.state = $t.to"
    assert state["classes"] == ["Transition", "WorkItem"], "w is implied by the range of transition_of"
    assert state["scope"] == {"t": {"classes": ["Transition"], "how": "declared"}, "w": {"classes": ["WorkItem"], "how": "implied"}}
    assert state["attributes"] == ["WorkItem.state"]
    overdue = by["intended-fact-overdue"]
    assert overdue["every_node"] is True and overdue["classes"] == []
    assert overdue["when"] == ["x where status = intended and as_of < $today-90d"]
    env = by["a-deployment-names-its-environment"]
    assert env["when"] == ["t is a Transition where to = deployed and environment is absent"]
    due = by["item-is-overdue"]
    assert due["when"] == ["w is a WorkItem where due < $today and state in open, blocked"]
    assert by["a-block-is-a-transition-to-blocked"]["when"] == ["b is a Block where to != blocked"]


def test_rules_are_looked_up_by_class_with_inheritance():
    vocabulary = _vocabulary("software-architecture")
    rules = list(ontologies.load_raw("software-architecture")["rules"])
    rules.append({"id": "asset-has-an-owner", "kind": "policy", "severity": "warn",
                  "when": [{"node": "a", "type": "Asset"}, {"not_edge": ["a", "owned_by", "*"]}],
                  "then": {"flag": "an asset must have an owner"}, "why": "Nobody answers for it otherwise.", "validated_by": "Ada"})
    m = _rules.model(rules, vocabulary)
    by = {r["id"]: r for r in m["rules"]}
    assert by["asset-has-an-owner"]["validated_by"] == "Ada" and by["asset-has-an-owner"]["classes"] == ["Asset"]
    risk = by["risk-reaches-system"]
    assert risk["when"] == ["edge r threatens c", "edge c part_of s"] and risk["then"] == "edge r threatens s"
    assert risk["relations"] == ["part_of", "threatens"] and risk["scope"]["r"] == {"classes": ["Risk"], "how": "implied"}
    assert "Component" in risk["scope"]["c"]["classes"] and "System" in risk["scope"]["s"]["classes"]
    assert set(m["by_class"]) == set(vocabulary["classes"]), "every declared class, even one no rule names"
    component = _rules.for_class(m, "Component")
    assert component["class"] == "Component"
    found = {r["id"]: r for r in component["rules"]}
    assert found["asset-has-an-owner"]["via"] == "Asset", "a rule on Asset applies to a Component, and says through which ancestor"
    assert found["risk-reaches-system"]["via"] is None, "named directly, through what threatens and part_of range over"
    assert [r["id"] for r in component["rules"]] == m["by_class"]["Component"]
    assert m["by_class"]["Role"] == [r["id"] for r in m["rules"] if r["every_node"]] == []
    assert _rules.for_class(m, "Nothing") is None
    empty = _rules.model([], vocabulary)
    assert empty["counts"] == {"rules": 0, "derive": 0, "policy": 0, "confirmed": 0} and empty["rules"] == []
    assert empty["by_class"] == {name: [] for name in vocabulary["classes"]} and empty["lineage"]["Component"] == ["Asset"]


# ---- lexicon (D3) ----

VOCABULARY = {
    "languages": ["en", "fr"],
    "classes": {"Asset": {"definition": "Something the estate owns."}, "System": {"subclass_of": ["Asset"]},
                "Component": {"subclass_of": ["Asset"], "label": {"en": "component", "fr": "composant"},
                              "alt_labels": {"en": ["module"], "fr": ["brique"]},
                              "definition": {"en": "A part of a system.", "fr": "Une partie d'un système."}}},
    "properties": {"part_of": {"domain": "Component", "range": "System", "inverse": "contains",
                               "label": {"en": "part of", "fr": "fait partie de"}, "definition": "Deployed inside."}},
    "attributes": {"Component": {"tier": {"type": "scheme:Tier", "label": {"fr": "niveau"}, "definition": "How central it is."}}},
    "schemes": {"Tier": {"definition": "How central a component is.", "concepts": {"core": {"label": {"en": "core", "fr": "cœur"}}}}},
}
ROWS = [{"phrase": "payments", "canonical": "payments", "target": "system.payments", "status": "current", "note": ""},
        {"phrase": "the platform", "canonical": "payments", "target": "system.payments", "status": "current", "note": ""},
        {"phrase": "legacy", "canonical": "legacy", "target": "", "status": "not_ingested", "note": "the old estate, not in the graph"}]
NODES = [{"id": "system.payments", "type": "System", "label": "Payments platform", "status": "current"}]


def test_every_term_carries_its_labels_in_every_declared_language():
    m = _lexicon.model(VOCABULARY, ROWS, NODES)
    assert m["languages"] == ["en", "fr"] and m["default_language"] == "en"
    assert m["counts"] == {"terms": 7, "phrases": 3, "languages": 2}
    terms = {(t["kind"], t["name"]): t for t in m["terms"]}
    component = terms[("class", "Component")]
    assert component["labels"] == {"en": "component", "fr": "composant"} and component["alt_labels"] == {"en": ["module"], "fr": ["brique"]}
    assert component["definition"] == {"en": "A part of a system.", "fr": "Une partie d'un système."}
    assert component["target"] == {"section": "ontology", "class": "Component"} and component["owner"] is None
    asset = terms[("class", "Asset")]
    assert asset["labels"] == {"en": "asset"} and asset["alt_labels"] == {} and asset["definition"] == {"en": "Something the estate owns."}
    part_of = terms[("relation", "part_of")]
    assert part_of["labels"]["fr"] == "fait partie de" and part_of["target"] == {"section": "ontology", "class": "Component", "relation": "part_of"}
    tier = terms[("attribute", "tier")]
    assert tier["owner"] == "Component" and tier["labels"] == {"en": "tier", "fr": "niveau"}
    assert tier["target"] == {"section": "ontology", "class": "Component", "attribute": "tier"}
    core = terms[("concept", "core")]
    assert core["owner"] == "Tier" and core["labels"] == {"en": "core", "fr": "cœur"}
    assert core["target"] == {"section": "ontology", "class": "Component", "attribute": "tier"}, "a concept lands where it is used"
    assert terms[("scheme", "Tier")]["target"] == {"section": "ontology", "class": "Component", "attribute": "tier"}
    assert [p["phrase"] for p in m["phrases"]] == ["legacy", "payments", "the platform"]
    payments = m["phrases"][1]
    assert payments == {"phrase": "payments", "canonical": "payments", "status": "current", "note": "", "target": "system.payments",
                        "label": "Payments platform", "type": "System"}
    assert m["phrases"][0]["target"] is None and m["phrases"][0]["label"] is None


def test_a_search_lands_on_the_element_the_word_names():
    m = _lexicon.model(VOCABULARY, ROWS, NODES)
    hit = _lexicon.search(m, "Composant")[0]
    assert hit["kind"] == "class" and hit["name"] == "Component" and hit["match"] == {"language": "fr", "text": "composant", "how": "label"}
    assert hit["target"] == {"section": "ontology", "class": "Component"}
    hit = _lexicon.search(m, "brique")[0]
    assert hit["name"] == "Component" and hit["match"]["how"] == "alt_label" and hit["match"]["language"] == "fr"
    hits = _lexicon.search(m, "payments")
    assert hits[0]["kind"] == "phrase" and hits[0]["target"] == {"section": "knowledge", "entity": "system.payments"}
    assert hits[0]["label"] == "Payments platform" and hits[0]["match"] == {"language": None, "text": "payments", "how": "phrase"}
    assert _lexicon.search(m, "the platform")[0]["target"]["entity"] == "system.payments"
    legacy = _lexicon.search(m, "legacy")[0]
    assert legacy["kind"] == "phrase" and legacy["target"] is None and legacy["status"] == "not_ingested"
    hits = _lexicon.search(m, "part")
    assert hits[0]["kind"] == "relation" and hits[0]["name"] == "part_of", "a prefix of 'part of'"
    assert [h["name"] for h in _lexicon.search(m, "comp")][0] == "Component", "prefix of the label"
    assert _lexicon.search(m, "core")[0]["kind"] == "concept" and _lexicon.search(m, "cœur")[0]["name"] == "core"
    assert _lexicon.search(m, "") == [] and _lexicon.search(m, "   ") == [] and _lexicon.search(m, "zzz") == []
    assert _lexicon.search(m, "part_of")[0]["name"] == "part_of", "the name itself finds it"
    exact = _lexicon.search(m, "component")
    assert exact[0]["name"] == "Component" and exact[0]["match"]["how"] == "label"


def test_a_vocabulary_without_languages_or_lexicon_still_projects():
    m = _lexicon.model({"classes": {"Thing": {"definition": ""}, "NFR": {}}, "properties": {"near": {}}}, [], [])
    assert m["languages"] == ["en"] and m["counts"] == {"terms": 3, "phrases": 0, "languages": 1}
    assert {t["name"]: t["labels"] for t in m["terms"]} == {"Thing": {"en": "thing"}, "NFR": {"en": "NFR"}, "near": {"en": "near"}}, "an acronym stays"
    assert _lexicon.search(m, "nfr")[0]["name"] == "NFR"
    assert _lexicon.search(m, "thing")[0]["target"] == {"section": "ontology", "class": "Thing"}
    assert _lexicon.search(m, "near")[0]["target"] == {"section": "ontology", "class": None, "relation": "near"}


# ---- served ----

def test_served_at_api_rules_and_api_lexicon_and_in_the_payload():
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        engine = _engine(project)
        server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("workbench", root), project_root=root, identity=project.config()).start()
        try:
            status, _c, text = _get(server.url + "/api/rules")
            assert status == 200, text
            m = json.loads(text)
            assert m["counts"]["rules"] >= 1 and "Component" in m["by_class"]
            status, _c, text = _get(server.url + "/api/rules?class=Component")
            assert status == 200 and "risk-reaches-system" in [r["id"] for r in json.loads(text)["rules"]]
            status, _c, text = _get(server.url + "/api/rules?class=Nothing")
            assert status == 404 and "Nothing" in text
            status, _c, text = _get(server.url + "/api/lexicon")
            assert status == 200, text
            lex = json.loads(text)
            assert "Component" in [t["name"] for t in lex["terms"]] and [p["phrase"] for p in lex["phrases"]] == ["payments", "the platform"]
            status, _c, text = _get(server.url + "/api/lexicon?q=the%20platform")
            assert status == 200 and json.loads(text)["hits"][0]["target"] == {"section": "knowledge", "entity": "system.payments"}
            status, _c, text = _get(server.url + "/api/lexicon?q=component")
            assert json.loads(text)["hits"][0]["target"] == {"section": "ontology", "class": "Component"}
            status, _c, text = _get(server.url + "/api/graph?passages=0")
            payload = json.loads(text)
            assert payload["rules"]["counts"] == m["counts"] and payload["terms"]["counts"] == lex["counts"]
            assert payload["vocabulary"]["languages"] == ["en"], "the payload's vocabulary says which languages it speaks"
            status, _c, text = _get(server.url + "/api/tools")
            assert "/api/rules" in text and "/api/lexicon" in text
        finally:
            server.stop()


def test_the_workbench_has_rules_and_lexicon_pages():
    with open(os.path.join(WORKBENCH, "workbench.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert "#/ontology/rules" in bundle and "#/ontology/lexicon" in bundle, "the routes are in the built bundle"
    assert os.path.exists(os.path.join(SRC, "views", "Rules.tsx")) and os.path.exists(os.path.join(SRC, "views", "Lexicon.tsx"))
    with open(os.path.join(SRC, "types.ts"), encoding="utf-8") as f:
        types = f.read()
    assert "RulesModel" in types and "LexiconModel" in types
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "/api/rules" in text and "/api/lexicon" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 25." in e2e and "/api/lexicon" in e2e
