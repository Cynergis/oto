"""The Neo4j layout of an OTO graph, computed with no database in sight."""
import json

from oto.targets import neo4j_map as m

CONFIG = {"classes": {"Claim": "c", "Party": "p"},
          "properties": {"filed_by": ["Claim", "Party", None, "x"]},
          "attributes": {"Claim": {"amount": ["number", "x"], "opened_on": ["date", "x"], "state": ["enum:open|closed", "x"],
                                   "count": ["integer", "x"], "flags": ["list", "x"], "urgent": ["boolean", "x"]}}}
GRAPH = {"nodes": [
    {"id": "claim.1", "type": "Claim", "label": "Claim 1", "aliases": ["C-1"], "summary": "s", "tags": ["t"],
     "attributes": {"amount": 12, "opened_on": "2026-03-01", "state": "open", "count": 2, "flags": ["a"], "urgent": True,
                    "colour": "red", "nested": {"x": 1}},
     "as_of": "2026-03-02", "valid_from": "2026-03-01", "status": "current", "source_doc": "memo", "sources": ["memo", "handbook"],
     "evidence": [{"doc": "memo", "where": "p.2", "quote": "q"}]},
    {"id": "claim.0", "type": "Claim", "label": "Claim 0", "status": "superseded", "valid_to": "2026-03-01",
     "superseded_by": "claim.1", "source_doc": "handbook", "sources": ["handbook"]},
    {"id": "party.1", "type": "Party", "label": "A. Person", "sources": ["memo"]},
    {"id": "ghost.1", "type": "Ghost", "label": "undeclared class, dropped"}],
    "edges": [{"from": "claim.1", "rel": "filed_by", "to": "party.1"}, {"from": "claim.1", "rel": "filed_by", "to": "ghost.1"}]}
DERIVED = {"derived_edges": [{"from": "party.1", "rel": "filed_by", "to": "claim.1", "derived_by": "r1", "premises": ["claim.1"]}],
           "derived_attributes": [{"node": "claim.1", "name": "risk", "value": "high", "derived_by": "r2", "premises": []}],
           "findings": [{"rule": "p1", "severity": "warn", "node": "claim.1", "message": "m"},
                        {"rule": "p2", "severity": "blocking", "node": None, "message": "graph-wide"}]}


def test_entities_keep_their_class_and_typed_attributes():
    planned = m.plan(GRAPH, CONFIG, "acme", 7, DERIVED)
    by = {n["props"]["id"]: n for n in planned["nodes"]}
    assert set(by) == {"claim.0", "claim.1", "party.1"}, "an undeclared class is dropped"
    claim = by["claim.1"]
    assert claim["label"] == "Claim" and claim["props"]["key"] == "acme:claim.1"
    p = claim["props"]
    assert p["amount"] == 12 and isinstance(p["amount"], int), "a whole number stays whole; 12 must not print as 12.0"
    assert p["degree"] == 2 and p["attributes_json"] == json.dumps(GRAPH["nodes"][0]["attributes"], ensure_ascii=False)
    assert p["count"] == 2 and p["urgent"] is True and p["flags"] == ["a"] and p["state"] == "open"
    assert p["opened_on"] == "2026-03-01" and claim["dates"] == ["opened_on"], "dates are converted by the loader"
    assert p["colour"] == "red" and p["nested"] == '{"x": 1}', "undeclared attributes are text"
    assert p["aliases_text"] == "C-1" and p["project"] == "acme" and p["build_seq"] == 7
    assert by["claim.0"]["props"]["status"] == "superseded" and by["claim.0"]["props"]["superseded_by"] == "claim.1"


def test_provenance_supersession_and_derived_facts_become_nodes_and_relationships():
    planned = m.plan(GRAPH, CONFIG, "acme", 7, DERIVED)
    rels = {(r["type"], r["a"], r["b"], r["props"]["kind"]) for r in planned["rels"]}
    assert ("filed_by", "acme:claim.1", "acme:party.1", "asserted") in rels
    assert ("filed_by", "acme:party.1", "acme:claim.1", "derived") in rels
    assert ("SUPERSEDES", "acme:claim.1", "acme:claim.0", "temporal") in rels
    assert ("CITES", "acme:claim.1", "acme:document:memo", "provenance") in rels
    assert ("filed_by", "acme:claim.1", "acme:ghost.1", "asserted") not in rels, "an edge to a dropped node is dropped"
    assert [d["slug"] for d in planned["documents"]] == ["handbook", "memo"]
    assert planned["evidence"][0]["key"] == "acme:claim.1:evidence:1" and planned["evidence"][0]["where"] == "p.2"
    assert planned["derived_attributes"][0]["value"] == '"high"' and planned["derived_attributes"][0]["derived_by"] == "r2"
    findings = planned["findings"]
    assert [f["rule"] for f in findings] == ["p1", "p2"] and findings[1]["entity"] is None
    derived_rel = next(r for r in planned["rels"] if r["props"]["kind"] == "derived")
    assert derived_rel["props"]["derived_by"] == "r1" and derived_rel["props"]["premises"] == ["claim.1"]


def test_the_plan_is_sorted_and_stable():
    a = m.plan(GRAPH, CONFIG, "acme", 7, DERIVED)
    shuffled = {"nodes": list(reversed(GRAPH["nodes"])), "edges": list(reversed(GRAPH["edges"]))}
    b = m.plan(shuffled, CONFIG, "acme", 7, DERIVED)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["labels"] == ["Claim", "Party"] and a["rel_types"] == ["CITES", "SUPERSEDES", "filed_by"]


def test_a_label_that_cypher_cannot_take_is_refused():
    import pytest
    bad = {"nodes": [{"id": "x", "type": "Bad Class", "label": "x"}], "edges": []}
    with pytest.raises(ValueError, match="cannot use"):
        m.plan(bad, {"classes": {"Bad Class": "x"}}, "acme", 1)


def test_summary_counts():
    planned = m.plan(GRAPH, CONFIG, "acme", 7, DERIVED)
    # 4 CITES, 1 SUPERSEDES, 1 asserted filed_by, 1 derived filed_by
    assert m.summary(planned) == {"nodes": 3, "relationships": 7, "evidence": 1, "documents": 2,
                                  "derived_attributes": 1, "findings": 2, "passages": 0}


def test_the_plan_carries_what_serving_reads():
    """Passages, lexicon rows and the ledger ride along, keyed per project, so the engine can answer
    from Neo4j alone."""
    planned = m.plan(GRAPH, CONFIG, "acme", 7, DERIVED,
                     passages=[{"path": "documents/b.md", "title": "B", "body": "b"}, {"path": "documents/a.md", "title": "A", "body": "a"}],
                     lexicon=[{"phrase": "the press", "canonical": "Press", "target": "claim.1", "status": "current", "note": ""}],
                     changelog=[{"at": "2026-01-01T00:00:00", "by": "me", "note": "n", "nodes_added": 1, "nodes_changed": 0,
                                 "edges_added": 0, "retired": "[]", "sources": "[]"}], schema_version=4)
    assert [p["key"] for p in planned["passages"]] == ["acme:passage:documents/a.md", "acme:passage:documents/b.md"]
    assert planned["lexicon"][0]["key"] == "acme:lexicon:1" and planned["lexicon"][0]["project"] == "acme"
    assert planned["changelog"][0]["key"] == "acme:changelog:1" and planned["schema_version"] == 4
    assert m.summary(planned)["passages"] == 2
    assert planned["evidence"][0]["index"] == 1, "evidence keeps its order, so a card lists it as authored"
