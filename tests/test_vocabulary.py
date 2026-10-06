"""Vocabulary versioning: what changed, what it breaks, and whether the graph conforms."""
import json
import os
import tempfile

import pytest

from oto.model import vocabulary as vocab
from oto.project import Project
from oto.scaffold import init

BASE = {
    "name": "KB",
    "ontology_version": 1,
    "classes": {"Machine": {"definition": "a machine"}, "Site": {"definition": "a place"}, "Crew": {"definition": "a team"}},
    "properties": {
        "installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts", "definition": "where it runs"},
        "operated_by": {"domain": "Machine", "range": "Crew", "definition": "who runs it"},
    },
    "temporal": {},
}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "h",
         "status": "current", "sources": ["h"]}


def _nodes():
    def node(nid, kind):
        return dict(id=nid, type=kind, label=nid, aliases=[], summary="s",
                    attributes={}, tags=[], **STAMP)
    return [node("m.1", "Machine"), node("m.2", "Machine"),
            node("s.1", "Site"), node("c.1", "Crew")]


def _edges():
    return [{"from": "m.1", "rel": "installed_at", "to": "s.1"},
            {"from": "m.2", "rel": "installed_at", "to": "s.1"},
            {"from": "m.1", "rel": "operated_by", "to": "c.1"}]


def _v(overrides=None):
    config = json.loads(json.dumps(BASE))
    for key, value in (overrides or {}).items():
        config[key] = value
    return vocab.Vocabulary.from_config(config)


# ---- diff ----

def test_no_change_is_reported_as_no_change():
    assert vocab.diff(_v(), _v()) == []


def test_a_removed_class_is_breaking_and_counts_its_nodes():
    after = _v()
    del after.classes["Crew"]
    changes = vocab.impact(vocab.diff(_v(), after), _nodes(), _edges())
    removed = [c for c in changes if c.kind == "class removed"]
    assert len(removed) == 1
    assert removed[0].severity == vocab.Change.BREAKING
    assert removed[0].affected == 1, "one Crew node exists"


def test_a_removed_relation_is_breaking_and_counts_its_edges():
    after = _v()
    del after.properties["installed_at"]
    changes = vocab.impact(vocab.diff(_v(), after), _nodes(), _edges())
    removed = [c for c in changes if c.kind == "relation removed"]
    assert removed and removed[0].severity == vocab.Change.BREAKING
    assert removed[0].affected == 2, "two installed_at edges exist"


def test_a_narrowed_domain_is_breaking():
    after = _v()
    after.properties["installed_at"] = {"domain": "Site", "range": "Site", "inverse": "hosts", "definition": "where it runs"}
    changes = vocab.impact(vocab.diff(_v(), after), _nodes(), _edges())
    assert any(c.kind == "domain changed" and c.severity == vocab.Change.BREAKING for c in changes)


def test_adding_is_additive_and_rewording_is_cosmetic():
    after = _v()
    after.properties["inspected_by"] = {"domain": "Machine", "range": "Crew", "definition": "who inspects"}
    after.classes["Machine"] = {"definition": "a stamping machine"}
    changes = vocab.diff(_v(), after)
    by_kind = {c.kind: c.severity for c in changes}
    assert by_kind["relation added"] == vocab.Change.ADDITIVE
    assert by_kind["class described"] == vocab.Change.COSMETIC
    assert not [c for c in changes if c.severity == vocab.Change.BREAKING]
    after.classes["Machine"] = {"definition": "a machine", "label": "stamping machine", "alt_labels": ["press"]}
    assert {c.kind: c.severity for c in vocab.diff(_v(), after)}["class relabelled"] == vocab.Change.COSMETIC


def test_breaking_changes_are_listed_first():
    after = _v()
    del after.classes["Crew"]
    after.classes["Machine"] = {"definition": "reworded"}
    after.properties["inspected_by"] = {"domain": "Machine", "range": "Site", "definition": "x"}
    changes = vocab.diff(_v(), after)
    severities = [c.severity for c in changes]
    assert severities == sorted(severities, key=lambda s: {"breaking": 0, "additive": 1,
                                                           "cosmetic": 2}[s])


def test_a_union_is_order_insensitive():
    """`A|B` and `B|A` declare the same thing, so reordering is not a change."""
    after = _v()
    after.properties["installed_at"] = {"domain": "Site|Machine", "range": "Site", "inverse": "hosts", "definition": "where it runs"}
    before = _v()
    before.properties["installed_at"] = {"domain": "Machine|Site", "range": "Site", "inverse": "hosts", "definition": "where it runs"}
    assert not [c for c in vocab.diff(before, after) if c.kind == "domain changed"]


# ---- conformance ----

def test_conformance_finds_a_domain_mismatch():
    """The integrity gate never checked this: a declared relation with the wrong endpoint type."""
    narrow = _v()
    narrow.properties["installed_at"] = {"domain": "Site", "range": "Site", "inverse": "hosts", "definition": "x"}
    report = vocab.conformance(narrow, _nodes(), _edges())
    assert report["checked"] == 3
    assert report["domain_violations"] == 2
    assert report["range_violations"] == 0


def test_conformance_ignores_undeclared_relations():
    """An undeclared relation is the integrity gate's job, not conformance's."""
    edges = _edges() + [{"from": "m.1", "rel": "not_declared", "to": "s.1"}]
    report = vocab.conformance(_v(), _nodes(), edges)
    assert report["checked"] == 3


def test_a_conformant_graph_reports_nothing():
    report = vocab.conformance(_v(), _nodes(), _edges())
    assert report["domain_violations"] == 0
    assert report["range_violations"] == 0


# ---- the lock ----

def test_lock_round_trips():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        project = Project.standard(root)
        assert vocab.read_lock(project) is None, "a fresh project has no baseline"
        vocab.write_lock(project, _v())
        back = vocab.read_lock(project)
        assert back.version == 1
        assert back.classes == _v().classes
        assert back.properties == _v().properties
        assert vocab.diff(back, _v()) == []


def test_preflight_reports_drift_without_failing():
    """A build that was passing must not start failing because a report was added."""
    from oto.validate.preflight import preflight

    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        project = Project.standard(root)
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump(BASE, f)
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": _nodes(), "edges": _edges()}, f)
        vocab.write_lock(project, _v())

        # Remove a class: breaking, but the graph still passes the integrity gate for what remains.
        config = json.loads(json.dumps(BASE))
        config["classes"].pop("Crew")
        config["properties"].pop("operated_by")
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        graph = {"nodes": [n for n in _nodes() if n["type"] != "Crew"],
                 "edges": [e for e in _edges() if e["rel"] != "operated_by"]}
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump(graph, f)

        summary = preflight(project)          # must NOT raise
        warnings = summary.get("warnings") or []
        assert any("breaking" in w for w in warnings), warnings


# ---- the form of a declaration ----

def test_a_declaration_in_any_other_form_is_refused_with_the_reason():
    assert vocab.shape_problems(BASE) == []
    problems = vocab.shape_problems({
        "classes": {"Machine": "a machine", "Site": {"definition": "a place", "descripton": "typo"}},
        "properties": {"installed_at": ["Machine", "Site", "hosts", "where it runs"]},
        "attributes": {"Machine": {"serial": ["string", "its number"]}},
        "temporal": {"asOf": ["date", "when"], "status": {"type": "text", "definition": "its state"}}})
    text = "\n".join(problems)
    for expected in ("class 'Machine' must be an object, {\"definition\": ..., \"label\": ...",
                     "class 'Site' carries unknown key(s) descripton",
                     "relation 'installed_at' must be an object, {\"domain\": ..., \"range\": ..., \"inverse\": ..., \"definition\": ..., \"label\"",
                     "attribute Machine.serial must be an object",
                     "temporal term 'asOf' must be an object",
                     "temporal term 'status': type must be one of date, string, ref"):
        assert expected in text, (expected, problems)


def test_the_build_and_the_catalog_refuse_a_vocabulary_in_another_form(tmp_path, monkeypatch):
    from oto.model import ontologies
    from oto.project import ProjectError
    from oto.validate.preflight import preflight

    with tempfile.TemporaryDirectory() as root:
        init(root, name="KB")
        with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
            json.dump(dict(BASE, classes={"Machine": "a machine"}), f)
        with pytest.raises(ProjectError, match="not in the form the engine reads"):
            preflight(Project.standard(root))

    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path))
    os.makedirs(tmp_path / "old")
    with open(tmp_path / "old" / "ontology.config.json", "w", encoding="utf-8") as f:
        json.dump({"name": "Old", "ontology_version": 1, "classes": {"Machine": "a machine"},
                   "properties": {"near": ["Machine", "Machine", None, "near"]}}, f)
    with open(tmp_path / "old" / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({"name": "old", "namespace": "https://example.org/ont/old#"}, f)
    assert any("not in the form the engine reads" in p and "class 'Machine' must be an object" in p
               for p in ontologies.self_check("old"))


# ---- the hierarchy ----

HIERARCHY = {
    "name": "KB", "ontology_version": 1,
    "classes": {"Asset": {"definition": "anything the estate runs"},
                "Machine": {"definition": "a machine", "subclass_of": ["Asset"]},
                "Press": {"definition": "a stamping machine", "subclass_of": ["Machine"]},
                "Site": {"definition": "a place"}, "Crew": {"definition": "a team"}},
    "properties": {"located_at": {"domain": "Asset", "range": "Site", "definition": "where it is"},
                   "installed_at": {"domain": "Machine", "range": "Site", "definition": "where it runs", "subproperty_of": "located_at"},
                   "operated_by": {"domain": "Machine", "range": "Crew", "definition": "who runs it"}},
    "attributes": {"Asset": {"tag": {"type": "string", "definition": "the asset tag"}},
                   "Press": {"tonnage": {"type": "number", "definition": "its force"}}},
    "temporal": {},
}


def test_a_class_covers_the_kinds_of_it_and_inherits_their_declarations():
    classes = HIERARCHY["classes"]
    assert vocab.ancestors(classes, "Press") == ["Machine", "Asset"] and vocab.ancestors(classes, "Site") == []
    assert vocab.covers(classes)["Asset"] == {"Asset", "Machine", "Press"} and vocab.covers(classes)["Site"] == {"Site"}
    assert set(vocab.declared_attributes(HIERARCHY, "Press")) == {"tonnage", "tag"}, "a parent's attributes apply"
    assert vocab.superproperties(HIERARCHY["properties"], "installed_at") == ["located_at"]
    assert vocab.relation_covers(HIERARCHY["properties"])["located_at"] == {"located_at", "installed_at"}
    assert vocab.hierarchy_problems(HIERARCHY) == []
    broken = json.loads(json.dumps(HIERARCHY))
    broken["classes"]["Asset"]["subclass_of"] = ["Press"]
    broken["classes"]["Crew"]["subclass_of"] = ["Team"]
    broken["properties"]["located_at"]["subproperty_of"] = "installed_at"
    text = "\n".join(vocab.hierarchy_problems(broken))
    assert "is a kind of itself" in text and "'Crew' is a kind of 'Team', which is not declared" in text
    assert "'located_at' specialises itself through 'installed_at'" in text


def test_conformance_and_values_follow_the_hierarchy():
    v = vocab.Vocabulary.from_config(HIERARCHY)
    nodes = [dict(id="p.1", type="Press", label="p", attributes={"tag": "A-1", "tonnage": 400}, **STAMP),
             dict(id="s.1", type="Site", label="s", attributes={}, **STAMP)]
    edges = [{"from": "p.1", "rel": "located_at", "to": "s.1"}]
    report = vocab.conformance(v, nodes, edges)
    assert report["domain_violations"] == 0, "a Press is an Asset"
    assert vocab.attribute_conformance(v, nodes)["mistyped"] == [] and v.attribute_type("Press", "tag") == "string"
    nodes[0]["attributes"]["tag"] = 7
    assert vocab.attribute_conformance(v, nodes)["mistyped"][0][1] == "tag", "the inherited type is checked"


def test_a_parent_removed_is_breaking_and_counts_what_it_covered():
    before = vocab.Vocabulary.from_config(HIERARCHY)
    after = json.loads(json.dumps(HIERARCHY))
    del after["classes"]["Machine"]["subclass_of"]
    after["properties"]["installed_at"].pop("subproperty_of")
    after["classes"]["Site"]["subclass_of"] = ["Asset"]
    nodes = [dict(id="p.1", type="Press", label="p", attributes={}, **STAMP), dict(id="m.1", type="Machine", label="m", attributes={}, **STAMP)]
    edges = [{"from": "p.1", "rel": "installed_at", "to": "m.1"}]
    changes = {c.kind: c for c in vocab.impact(vocab.diff(before, vocab.Vocabulary.from_config(after)), nodes, edges,
                                               vocab.Vocabulary.from_config(after))}
    assert changes["superclass removed"].severity == vocab.Change.BREAKING and changes["superclass removed"].affected == 2
    assert changes["superclass added"].severity == vocab.Change.ADDITIVE and changes["superclass added"].subject == "Site"
    assert changes["superproperty removed"].severity == vocab.Change.BREAKING and changes["superproperty removed"].affected == 1


def test_a_changed_definition_asks_the_person_who_confirmed_it_again():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="KB")
        config = dict(BASE)
        with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
        with open(os.path.join(root, "ontology.rationale.json"), "w", encoding="utf-8") as f:
            json.dump({"classes": {"Machine": {"question": "q", "why": "because the line is not what fails",
                                               "alternatives": "", "validated_by": "R. Plant"}}, "properties": {}}, f)
        project = Project.standard(root)
        vocab.write_lock(project, vocab.Vocabulary.from_config(config), rules=[])
        current = json.loads(json.dumps(config))
        current["classes"]["Machine"]["definition"] = "a machine, reworded"
        from oto.model import rationale as _rationale
        asked = vocab.reconfirm(vocab.read_lock(project), vocab.Vocabulary.from_config(current), _rationale.load(project))
        assert asked == [("class", "Machine", "R. Plant")]
        record = _rationale.load(project); record["classes"]["Machine"]["validated_by"] = "R. Plant, again"
        assert vocab.reconfirm(vocab.read_lock(project), vocab.Vocabulary.from_config(current), record) == []


# ---- controlled values ----

SCHEMES = {"ClaimState": {"definition": "Where a claim is.", "concepts": {
    "open": {"label": "Open", "definition": "Being handled."}, "reopened": {"label": "Reopened", "broader": "open"},
    "closed": {"label": "Closed"}}}}


def test_a_scheme_is_an_enum_whose_values_mean_something():
    assert vocab.check_value("scheme:ClaimState", "reopened", SCHEMES) is None
    assert vocab.check_value("scheme:ClaimState", "lost", SCHEMES) == "expected one of open|reopened|closed"
    assert vocab.concepts_of("enum:a|b") == {"a": {}, "b": {}}, "an enum is a scheme whose concepts carry nothing"
    assert vocab.top_concept(SCHEMES["ClaimState"]["concepts"], "reopened") == "open"
    assert vocab.scheme_problems({"schemes": SCHEMES}) == []
    with pytest.raises(ValueError, match="scheme 'Nope' is not declared"):
        vocab.parse_attribute_type("scheme:Nope", SCHEMES)
    problems = vocab.declaration_problems({"Claim": {}}, {"Claim": {"state": {"type": "scheme:Nope", "definition": ""}}}, SCHEMES)
    assert any("scheme 'Nope' is not declared" in p for p in problems)
    broken = {"schemes": {"X": {"definition": "d", "concepts": {"a": {"broader": "zz"}, "b": {"broader": "c"}, "c": {"broader": "b"}}},
                          "Empty": {"definition": "d", "concepts": {}}}}
    text = "\n".join(vocab.scheme_problems(broken))
    assert "X.a is narrower than 'zz', which the scheme does not declare" in text and "broader than itself" in text
    assert "scheme 'Empty' declares no concepts" in text


def test_a_concept_removed_is_breaking_and_counts_the_values_that_use_it():
    config = dict(BASE, schemes=SCHEMES, attributes={"Machine": {"state": {"type": "scheme:ClaimState", "definition": "where"}}})
    before = vocab.Vocabulary.from_config(config)
    after = json.loads(json.dumps(config))
    del after["schemes"]["ClaimState"]["concepts"]["closed"]
    after["schemes"]["ClaimState"]["concepts"]["reopened"]["broader"] = None
    after["schemes"]["ClaimState"]["concepts"]["paid"] = {"label": "Paid"}
    nodes = [dict(id="m.%d" % i, type="Machine", label="m", attributes={"state": s}, **STAMP) for i, s in enumerate(("closed", "closed", "open"))]
    changes = {c.kind: c for c in vocab.impact(vocab.diff(before, vocab.Vocabulary.from_config(after)), nodes, [], vocab.Vocabulary.from_config(after))}
    assert changes["concept removed"].severity == vocab.Change.BREAKING and changes["concept removed"].affected == 2
    assert changes["concept added"].severity == vocab.Change.ADDITIVE and changes["concept re-parented"].severity == vocab.Change.ADDITIVE

