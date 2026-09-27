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
    "classes": {"Machine": "a machine", "Site": "a place", "Crew": "a team"},
    "properties": {
        "installed_at": ["Machine", "Site", "hosts", "where it runs"],
        "operated_by": ["Machine", "Crew", None, "who runs it"],
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
    after.properties["installed_at"] = ("Site", "Site", "hosts", "where it runs")
    changes = vocab.impact(vocab.diff(_v(), after), _nodes(), _edges())
    assert any(c.kind == "domain changed" and c.severity == vocab.Change.BREAKING for c in changes)


def test_adding_is_additive_and_rewording_is_cosmetic():
    after = _v()
    after.properties["inspected_by"] = ("Machine", "Crew", None, "who inspects")
    after.classes["Machine"] = "a stamping machine"
    changes = vocab.diff(_v(), after)
    by_kind = {c.kind: c.severity for c in changes}
    assert by_kind["relation added"] == vocab.Change.ADDITIVE
    assert by_kind["class described"] == vocab.Change.COSMETIC
    assert not [c for c in changes if c.severity == vocab.Change.BREAKING]


def test_breaking_changes_are_listed_first():
    after = _v()
    del after.classes["Crew"]
    after.classes["Machine"] = "reworded"
    after.properties["inspected_by"] = ("Machine", "Site", None, "x")
    changes = vocab.diff(_v(), after)
    severities = [c.severity for c in changes]
    assert severities == sorted(severities, key=lambda s: {"breaking": 0, "additive": 1,
                                                           "cosmetic": 2}[s])


def test_a_union_is_order_insensitive():
    """`A|B` and `B|A` declare the same thing, so reordering is not a change."""
    after = _v()
    after.properties["installed_at"] = ("Site|Machine", "Site", "hosts", "where it runs")
    before = _v()
    before.properties["installed_at"] = ("Machine|Site", "Site", "hosts", "where it runs")
    assert not [c for c in vocab.diff(before, after) if c.kind == "domain changed"]


# ---- conformance ----

def test_conformance_finds_a_domain_mismatch():
    """The integrity gate never checked this: a declared relation with the wrong endpoint type."""
    narrow = _v()
    narrow.properties["installed_at"] = ("Site", "Site", "hosts", "x")
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
