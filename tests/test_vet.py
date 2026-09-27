# -*- coding: utf-8 -*-
"""The provenance audit, and the guards that stop it deleting real knowledge."""
import pytest

from oto.curate import vet


def _node(node_id, sources, source_doc=None, label=None):
    return {"id": node_id, "type": "Thing", "label": label or node_id,
            "summary": "s", "status": "current", "as_of": "2026-01-01",
            "sources": list(sources), "source_doc": source_doc or (sources[0] if sources else None)}


@pytest.fixture
def graph():
    return {
        "nodes": [
            _node("live.one", ["kept-doc"]),
            _node("mixed.one", ["kept-doc", "gone-doc"]),
            _node("pure.attested", ["gone-doc"]),
            _node("pure.orphan", ["gone-doc"]),
            _node("marked.one", ["manual-update-2026-03"]),
        ],
        "edges": [
            {"from": "pure.attested", "to": "live.one", "rel": "relates"},
        ],
    }


# ---- the audit ----

def test_the_audit_separates_a_lost_fact_from_a_stale_citation(graph):
    report = vet.audit(graph, {"kept-doc"})
    assert report["dead"] == {"gone-doc": 3}
    assert [e["id"] for e in report["mixed"]] == ["mixed.one"]
    assert sorted(e["id"] for e in report["pure"]) == ["pure.attested", "pure.orphan"]


def test_a_curation_marker_is_never_a_dead_citation(graph):
    """A tag such as `manual-update-2026-03` is a deliberate marker, not a missing file."""
    report = vet.audit(graph, {"kept-doc"})
    assert "manual-update-2026-03" not in report["dead"]
    assert report["curation"] == {"manual-update-2026-03": 1}
    assert "marked.one" not in [e["id"] for e in report["pure"]]


def test_a_whitelisted_alias_is_accepted(graph):
    """An unmatched tag is usually an alias. Whitelisting it must clear it completely."""
    report = vet.audit(graph, {"kept-doc"}, ["gone-doc"])
    assert report["dead"] == {}
    assert report["pure"] == [] and report["mixed"] == []


# ---- reading the graph's own edge names ----

def test_neighbours_are_found_through_the_graph_edge_names(graph):
    """The graph says from/to and the database says src/dst. Reading the wrong pair finds nothing."""
    assert vet.attesting_neighbours(graph, "pure.attested", {"kept-doc"}) == ["kept-doc"]
    assert vet.attesting_neighbours(graph, "pure.orphan", {"kept-doc"}) == []


def test_an_edge_with_neither_endpoint_name_raises(graph):
    """Silence is the failure mode this replaces: no neighbours found, everything called orphaned."""
    graph["edges"] = [{"src": "pure.attested", "dst": "live.one", "rel": "relates"}]
    with pytest.raises(KeyError):
        vet.attesting_neighbours(graph, "pure.attested", {"kept-doc"})


# ---- the plan ----

def test_each_at_risk_fact_reaches_exactly_one_outcome(graph):
    report = vet.audit(graph, {"kept-doc"})
    actions, unknown = vet.plan(graph, report)
    assert [e["id"] for e in actions["resourced"]] == ["pure.attested"]
    assert [e["id"] for e in actions["orphaned"]] == ["pure.orphan"]
    assert actions["removed"] == []
    assert unknown == []


def test_nothing_is_removed_unless_it_is_named(graph):
    """The original tool removed by default and gutted an org chart. This one does not."""
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report)
    assert actions["removed"] == []
    actions, _ = vet.plan(graph, report, remove=["pure.orphan"])
    assert [e["id"] for e in actions["removed"]] == ["pure.orphan"]


def test_a_fallback_catches_what_no_neighbour_attests(graph):
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report, fallback="kept-doc")
    assert [e["id"] for e in actions["fallback"]] == ["pure.orphan"]
    assert actions["orphaned"] == []


def test_removing_a_node_that_is_not_at_risk_is_reported(graph):
    """Deleting a well-sourced node is not a provenance fix, so vet must not be the tool for it."""
    report = vet.audit(graph, {"kept-doc"})
    _, unknown = vet.plan(graph, report, remove=["live.one"])
    assert unknown == ["live.one"]


# ---- the rewrite ----

def test_an_orphaned_fact_is_left_exactly_as_it_was(graph):
    """The report promises it is left alone. An earlier version stripped it to no sources at all."""
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report)
    fresh = vet.rewrite(graph, report, actions, "2026-08-25")
    before = [n for n in graph["nodes"] if n["id"] == "pure.orphan"][0]
    after = [n for n in fresh["nodes"] if n["id"] == "pure.orphan"][0]
    assert after == before


def test_a_stale_citation_is_stripped_and_the_live_one_kept(graph):
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report)
    fresh = vet.rewrite(graph, report, actions, "2026-08-25")
    node = [n for n in fresh["nodes"] if n["id"] == "mixed.one"][0]
    assert node["sources"] == ["kept-doc"]
    assert node["source_doc"] == "kept-doc"
    assert node["as_of"] == "2026-08-25"


def test_an_inferred_citation_is_marked_as_inferred(graph):
    """Adjacency is not attestation. A guess that looks like a source is the worst outcome here."""
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report)
    fresh = vet.rewrite(graph, report, actions, "2026-08-25")
    node = [n for n in fresh["nodes"] if n["id"] == "pure.attested"][0]
    assert node["sources"] == ["kept-doc"]
    assert node["provenance"] == "inferred"
    assert "Adjacency is not attestation" in node["provenance_note"]
    assert "gone-doc" in node["provenance_note"], "it must name what was lost"


def test_removing_a_node_drops_its_edges(graph):
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report, remove=["pure.attested"])
    assert len(vet.orphaned_edges(graph, ["pure.attested"])) == 1
    fresh = vet.rewrite(graph, report, actions, "2026-08-25")
    assert fresh["edges"] == []
    assert "pure.attested" not in [n["id"] for n in fresh["nodes"]]


def test_the_input_graph_is_not_modified(graph):
    import copy

    original = copy.deepcopy(graph)
    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report, remove=["pure.orphan"])
    vet.rewrite(graph, report, actions, "2026-08-25")
    assert graph == original


# ---- the review gate must see it ----

def test_the_curate_gate_reports_a_provenance_change(graph):
    """`oto vet` only edits provenance. While these fields were unwatched the gate printed ~0."""
    from oto.curate import diff

    report = vet.audit(graph, {"kept-doc"})
    actions, _ = vet.plan(graph, report)
    fresh = vet.rewrite(graph, report, actions, "2026-08-25")
    summary = diff.summarize(graph, fresh)
    changed = dict(summary["nodes_reprovenanced"])
    assert "mixed.one" in changed
    assert "pure.attested" in changed
    assert summary["nodes_changed"] == [], "no fact changed, only who attests it"
