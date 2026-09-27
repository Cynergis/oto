"""Widening proposals: triage rather than bless, and never apply."""
import json
import os
import tempfile

from oto.model import vocabulary as vocab, widen
from oto.project import Project
from oto.scaffold import init

CONFIG = {
    "ontology_version": 3,
    "classes": {"A": "a", "B": "b", "C": "c", "D": "d"},
    "properties": {"links": ["A", "B", None, "a to b"]},
}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "d",
         "status": "current", "sources": ["d"]}


def _nodes(spec):
    return [dict(id=nid, type=kind, label=nid, aliases=[], summary="s", attributes={},
                 tags=[], **STAMP) for nid, kind in spec]


def test_a_frequent_pattern_is_proposed_for_widening():
    nodes = _nodes([("c%d" % i, "C") for i in range(6)] + [("b1", "B")])
    edges = [{"from": "c%d" % i, "rel": "links", "to": "b1"} for i in range(6)]
    findings = widen.analyse(CONFIG, nodes, edges, frequent=5)
    assert len(findings) == 1
    assert findings[0]["widen_domain"] == {"C": 6}
    assert findings[0]["inspect_domain"] == {}


def test_a_rare_pattern_is_left_for_a_person():
    """Widening a mistake hides it permanently."""
    nodes = _nodes([("c1", "C"), ("b1", "B")])
    edges = [{"from": "c1", "rel": "links", "to": "b1"}]
    findings = widen.analyse(CONFIG, nodes, edges, frequent=5)
    assert findings[0]["inspect_domain"] == {"C": 1}
    assert findings[0]["widen_domain"] == {}


def test_a_type_never_lands_in_both_buckets():
    """Thresholding per endpoint PAIR put the same type in both, which is nonsense."""
    nodes = _nodes([("c%d" % i, "C") for i in range(6)] + [("b1", "B"), ("d1", "D")])
    edges = [{"from": "c%d" % i, "rel": "links", "to": "b1"} for i in range(4)]
    edges += [{"from": "c%d" % i, "rel": "links", "to": "d1"} for i in range(4, 6)]
    findings = widen.analyse(CONFIG, nodes, edges, frequent=5)
    finding = findings[0]
    assert set(finding["widen_domain"]) & set(finding["inspect_domain"]) == set()
    assert finding["widen_domain"] == {"C": 6}, "counts must aggregate across partners"


def test_the_proposal_resolves_the_frequent_violations_only():
    nodes = _nodes([("c%d" % i, "C") for i in range(6)] + [("b1", "B"), ("d1", "D")])
    edges = [{"from": "c%d" % i, "rel": "links", "to": "b1"} for i in range(6)]
    edges += [{"from": "c0", "rel": "links", "to": "d1"}]          # rare range violation
    findings = widen.analyse(CONFIG, nodes, edges, frequent=5)
    proposed, changed = widen.propose(CONFIG, findings)
    assert changed == ["links"]

    before = vocab.conformance(vocab.Vocabulary.from_config(CONFIG), nodes, edges)
    after = vocab.conformance(vocab.Vocabulary.from_config(proposed), nodes, edges)
    assert before["domain_violations"] == 7
    assert after["domain_violations"] == 0, "the frequent pattern should be resolved"
    assert after["range_violations"] == 1, "the rare one must be left for a person"


def test_a_widening_never_invalidates_an_existing_edge():
    nodes = _nodes([("c%d" % i, "C") for i in range(6)] + [("b1", "B")])
    edges = [{"from": "c%d" % i, "rel": "links", "to": "b1"} for i in range(6)]
    findings = widen.analyse(CONFIG, nodes, edges, frequent=5)
    proposed, _changed = widen.propose(CONFIG, findings)
    before = set(vocab.Vocabulary.from_config(CONFIG).domain("links"))
    after = set(vocab.Vocabulary.from_config(proposed).domain("links"))
    assert before <= after, "a widening must only add, never remove"


def test_the_proposal_raises_the_version():
    """A vocabulary change with no version bump makes the lock meaningless."""
    nodes = _nodes([("c%d" % i, "C") for i in range(6)] + [("b1", "B")])
    edges = [{"from": "c%d" % i, "rel": "links", "to": "b1"} for i in range(6)]
    proposed, _ = widen.propose(CONFIG, widen.analyse(CONFIG, nodes, edges, frequent=5))
    assert proposed["ontology_version"] == 4


def test_a_conformant_graph_produces_no_findings():
    nodes = _nodes([("a1", "A"), ("b1", "B")])
    edges = [{"from": "a1", "rel": "links", "to": "b1"}]
    assert widen.analyse(CONFIG, nodes, edges) == []


def test_an_undeclared_relation_is_not_this_command_s_job():
    """That is the integrity gate's job. Reporting it here would duplicate and confuse."""
    nodes = _nodes([("a1", "A"), ("b1", "B")])
    edges = [{"from": "a1", "rel": "not_declared", "to": "b1"}]
    assert widen.analyse(CONFIG, nodes, edges) == []


def test_the_proposal_is_written_beside_the_config_not_over_it():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        project = Project.standard(root)
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f)
        before = open(project.ontology_config_path, encoding="utf-8").read()

        path = widen.write_proposal(project, dict(CONFIG, ontology_version=4))
        assert path != project.ontology_config_path
        assert os.path.exists(path)
        assert open(project.ontology_config_path, encoding="utf-8").read() == before, \
            "the real config must be untouched"
