"""An attribute may declare a `default` and its former values (`was`): an absent value reads as the default,
a former value reads as the value it became, an asserted value beats a derived one which beats the default,
and the vocabulary diff reads a rename of values as additive and a dropped value as breaking. Tested on a
small claims vocabulary; the work pack of the registry is the first user of these (its states)."""
import json

from oto.model import vocabulary as _vocab
from oto.reason import engine, match, questions, rules as _rules



def _node(nid, type_, status="current", **attrs):
    return {"id": nid, "type": type_, "label": nid, "attributes": attrs, "status": status,
            "as_of": "2026-10-01", "valid_from": "2026-10-01", "source_doc": "plan"}


# ---- the vocabulary: `default` and `was` on an attribute ----

CLAIMS = {"ontology_version": 1, "name": "t",
          "classes": {"Claim": {"definition": "x"}, "Event": {"definition": "x"}},
          "properties": {"of": {"domain": "Event", "range": "Claim", "definition": "x"}},
          "attributes": {"Claim": {"state": {"type": "enum:open|closed", "definition": "x", "default": "open",
                                             "was": {"new": "open", "settled": "closed"}}},
                         "Event": {"to": {"type": "enum:open|closed", "definition": "x"}}}}


def test_an_attribute_may_declare_a_default_and_its_former_values():
    assert _vocab.declaration_problems(CLAIMS["classes"], CLAIMS["attributes"]) == []
    bad = json.loads(json.dumps(CLAIMS))
    bad["attributes"]["Claim"]["state"]["default"] = "pending"
    assert any("default" in p and "pending" in p for p in _vocab.declaration_problems(bad["classes"], bad["attributes"]))
    bad = json.loads(json.dumps(CLAIMS))
    bad["attributes"]["Claim"]["state"]["was"] = {"new": "pending"}
    assert any("was" in p and "pending" in p for p in _vocab.declaration_problems(bad["classes"], bad["attributes"]))
    bad["attributes"]["Claim"]["state"]["was"] = ["new"]
    assert any("`was`" in p for p in _vocab.declaration_problems(bad["classes"], bad["attributes"]))


def test_a_former_value_still_fits_and_reads_as_the_current_one():
    spec = CLAIMS["attributes"]["Claim"]["state"]
    assert _vocab.check_value(spec["type"], "new", former=spec["was"]) is None
    assert "open|closed" in _vocab.check_value(spec["type"], "lost", former=spec["was"])
    report = _vocab.attribute_conformance(_vocab.Vocabulary.from_config(CLAIMS),
                                          [_node("claim.1", "Claim", state="settled"), _node("claim.2", "Claim", state="lost")])
    assert [m[0] for m in report["mistyped"]] == ["claim.2"]
    graph = match.Graph([_node("claim.1", "Claim", state="settled"), _node("claim.2", "Claim")],
                        [], declared=questions.declared_names(CLAIMS))
    assert graph.attribute("claim.1", "state") == "closed", "a former value is read as the value it became"
    assert graph.attribute("claim.2", "state") == "open", "an absent value is the default"


def test_asserted_beats_derived_beats_default():
    nodes = [_node("claim.1", "Claim"), _node("claim.2", "Claim", state="closed"), _node("event.1", "Event", to="closed")]
    edges = [{"from": "event.1", "rel": "of", "to": "claim.1"}, {"from": "event.1", "rel": "of", "to": "claim.2"}]
    rule = {"id": "state-follows-event", "kind": "derive", "why": "x",
            "when": [{"node": "e", "type": "Event"}, {"edge": ["e", "of", "c"]}],
            "then": {"attribute": ["c", "state", "$e.to"]}}
    assert _rules.problems([rule], CLAIMS) == []
    result = engine.run([rule], nodes, edges, declared=questions.declared_names(CLAIMS))
    assert [(a["node"], a["value"]) for a in result["attributes"]] == [("claim.1", "closed")], \
        "the value comes from the bound node; the asserted one on claim.2 wins"
    graph = match.Graph(nodes, edges, {"claim.1": {"state": "closed"}}, declared=questions.declared_names(CLAIMS))
    assert graph.attribute("claim.1", "state") == "closed", "derived beats the default"
    unbound = dict(rule, then={"attribute": ["c", "state", "$x.to"]})
    assert any("$x" in p or "'x'" in p for p in _rules.problems([unbound], CLAIMS))
    absent = engine.run([rule], [_node("claim.3", "Claim"), _node("event.2", "Event")],
                        [{"from": "event.2", "rel": "of", "to": "claim.3"}], declared=questions.declared_names(CLAIMS))
    assert absent["attributes"] == [], "a reference to a value the node does not carry derives nothing"


def test_the_diff_reads_a_rename_of_values_as_additive_and_a_dropped_value_as_breaking():
    old = _vocab.Vocabulary.from_config({"ontology_version": 1, "classes": {"Claim": {"definition": "x"}}, "properties": {},
                                         "attributes": {"Claim": {"state": {"type": "enum:new|open|settled|void", "definition": "x"}}}})
    new = _vocab.Vocabulary.from_config(CLAIMS)
    changes = {(c.kind, c.subject): c for c in _vocab.diff(old, new)}
    renamed = changes[("attribute values renamed", "Claim.state")]
    assert renamed.severity == _vocab.Change.ADDITIVE and "new -> open" in renamed.detail and "settled -> closed" in renamed.detail
    dropped = changes[("attribute values removed", "Claim.state")]
    assert dropped.severity == _vocab.Change.BREAKING and "void" in dropped.detail
    assert ("attribute type changed", "Claim.state") not in changes
    with_count = _vocab.impact(list(changes.values()), [_node("c.1", "Claim", state="void"), _node("c.2", "Claim", state="new")], [], new)
    assert next(c for c in with_count if c.kind == "attribute values removed").affected == 1
