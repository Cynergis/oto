"""Matching and forward chaining: deterministic, explainable, and asserted facts always win."""
import pytest

from oto.reason import engine, match


def _node(nid, kind, **attrs):
    return {"id": nid, "type": kind, "label": nid, "attributes": attrs, "status": "current",
            "source_doc": "handbook", "evidence": [{"doc": "handbook", "where": "p.1", "quote": "q"}]}


def _edge(a, rel, b, **over):
    e = {"from": a, "rel": rel, "to": b}
    e.update(over)
    return e


NODES = [_node("risk.1", "Risk"), _node("component.api", "Component"), _node("system.pay", "System"),
         _node("component.job", "Component"), _node("interface.v2", "Interface"),
         _node("claim.1", "Claim", state="open", amount=12000), _node("claim.2", "Claim", state="open", amount=500),
         _node("decision.1", "DecisionRecord"), _node("decision.2", "DecisionRecord"), _node("doc.1", "Document")]
EDGES = [_edge("risk.1", "threatens", "component.api"), _edge("component.api", "part_of", "system.pay"),
         _edge("component.job", "consumes", "interface.v2"), _edge("component.api", "exposes", "interface.v2"),
         _edge("decision.1", "documented_in", "doc.1")]

RISK = {"id": "risk-reaches-system", "kind": "derive",
        "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
        "then": {"edge": ["r", "threatens", "s"]}, "why": "x"}
DEPENDS = {"id": "consumer-depends-on-provider", "kind": "derive",
           "when": [{"edge": ["a", "consumes", "i"]}, {"edge": ["b", "exposes", "i"]}],
           "then": {"edge": ["a", "depends_on", "b"]}, "why": "x"}
HIGH = {"id": "high-value", "kind": "derive",
        "when": [{"node": "c", "type": "Claim", "where": {"state": "open", "amount": {">": 10000}}}],
        "then": {"attribute": ["c", "risk", "high"]}, "why": "x"}
DOCUMENTED = {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
              "when": [{"node": "d", "type": "DecisionRecord"}, {"not_edge": ["d", "documented_in", "*"]}],
              "then": {"flag": "cite the document"}, "why": "x"}


# ---- matching ----

def test_operators_against_each_type():
    assert match.compare("=", "open", "open") and not match.compare("=", "open", "closed")
    assert match.compare("!=", "open", "closed")
    assert match.compare(">", 12000, 10000) and not match.compare(">", 500, 10000)
    assert match.compare("<=", "2026-01-01", "2026-06-01"), "dates compare as dates"
    assert match.compare("in", "open", ["open", "reopened"]) and not match.compare("in", "lost", ["open"])
    assert match.compare("contains", ["a", "b"], "a") and match.compare("contains", "hello world", "world")
    assert not match.compare(">", None, 1), "an absent value fits nothing"
    assert not match.compare(">", "twelve", 1), "a value that cannot be compared does not match"


def test_superseded_facts_are_invisible_to_rules():
    nodes = NODES + [_node("risk.old", "Risk")]
    nodes[-1]["status"] = "superseded"
    edges = EDGES + [_edge("risk.old", "threatens", "component.api"),
                     _edge("risk.1", "threatens", "component.job", status="superseded")]
    graph = match.Graph(nodes, edges)
    assert "risk.old" not in graph.nodes
    assert ("risk.1", "threatens", "component.job") not in graph.keys


def test_bindings_join_across_patterns_in_a_stable_order():
    graph = match.Graph(NODES, EDGES)
    found = match.matches(graph, RISK["when"])
    assert [(b["r"], b["c"], b["s"]) for b, _ in found] == [("risk.1", "component.api", "system.pay")]
    assert match.matches(graph, RISK["when"]) == found, "the same graph gives the same order twice"


def test_relation_alternation_and_the_wildcard():
    graph = match.Graph(NODES, EDGES)
    found = match.matches(graph, [{"edge": ["x", "consumes|exposes", "interface.v2".replace(".", "_") if False else "i"]}])
    assert sorted(b["x"] for b, _ in found) == ["component.api", "component.job"]
    assert len(match.matches(graph, [{"edge": ["*", "part_of", "s"]}])) == 1


# ---- the engine ----

def test_derives_the_transitive_fact_with_its_premises_and_depth():
    result = engine.run([RISK], NODES, EDGES)
    assert len(result["edges"]) == 1
    derived = result["edges"][0]
    assert (derived["from"], derived["rel"], derived["to"], derived["status"]) == ("risk.1", "threatens", "system.pay", "derived")
    assert derived["derived_by"] == "risk-reaches-system" and derived["depth"] == 1
    assert derived["premises"] == ["component.api", "risk.1", "system.pay",
                                   "risk.1 -threatens-> component.api", "component.api -part_of-> system.pay"]
    assert result["per_rule"]["risk-reaches-system"]["derived"] == 1


def test_reaches_the_fixpoint_along_a_chain_and_records_depth():
    chain = [_node("a", "Component"), _node("b", "Component"), _node("c", "Component"), _node("d", "Component")]
    edges = [_edge("a", "reports_to", "b"), _edge("b", "reports_to", "c"), _edge("c", "reports_to", "d")]
    rule = {"id": "up", "kind": "derive",
            "when": [{"edge": ["x", "reports_to", "y"]}, {"edge": ["y", "reports_to|reports_up_to", "z"]}],
            "then": {"edge": ["x", "reports_up_to", "z"]}, "why": "x"}
    result = engine.run([rule], chain, edges)
    pairs = sorted((e["from"], e["to"]) for e in result["edges"])
    assert pairs == [("a", "c"), ("a", "d"), ("b", "d")]
    assert max(e["depth"] for e in result["edges"]) == 2 and result["rounds"] >= 2


def test_a_derived_edge_that_the_document_already_states_is_dropped():
    edges = EDGES + [_edge("risk.1", "threatens", "system.pay")]
    result = engine.run([RISK], NODES, edges)
    assert result["edges"] == []


def test_a_derived_attribute_never_overwrites_an_asserted_one():
    result = engine.run([HIGH], NODES, EDGES)
    assert [(a["node"], a["name"], a["value"]) for a in result["attributes"]] == [("claim.1", "risk", "high")]
    stubborn = {"id": "wrong", "kind": "derive", "when": [{"node": "c", "type": "Claim"}],
                "then": {"attribute": ["c", "state", "closed"]}, "why": "x"}
    result = engine.run([stubborn], NODES, EDGES)
    assert result["attributes"] == [], "state is asserted on every claim"


def test_superseding_a_premise_removes_the_derivation_on_the_next_run():
    edges = [dict(e) for e in EDGES]
    result = engine.run([RISK], NODES, edges)
    assert result["edges"]
    edges[1]["status"] = "superseded"                       # component.api part_of system.pay retired
    assert engine.run([RISK], NODES, edges)["edges"] == []


def test_policy_rules_flag_and_change_nothing():
    result = engine.run([DOCUMENTED], NODES, EDGES)
    assert [(f["rule"], f["node"], f["severity"]) for f in result["findings"]] == \
        [("decision-is-documented", "decision.2", "warn")]
    assert result["edges"] == [] and result["attributes"] == []


def test_two_rules_compose_and_the_result_is_deterministic():
    first = engine.run([RISK, DEPENDS, HIGH, DOCUMENTED], NODES, EDGES)
    second = engine.run([RISK, DEPENDS, HIGH, DOCUMENTED], list(reversed(NODES)), list(reversed(EDGES)))
    strip = lambda r: {k: r[k] for k in ("edges", "attributes", "findings")}
    assert strip(first) == strip(second)
    assert sorted(e["rel"] for e in first["edges"]) == ["depends_on", "threatens"]


def test_a_rule_set_that_never_settles_is_refused():
    grow = {"id": "grow", "kind": "derive", "when": [{"node": "c", "type": "Component"}],
            "then": {"attribute": ["c", "n", 1]}, "why": "x"}
    engine.run([grow], NODES, EDGES)                        # attributes settle: set once, then skipped
    monkey = engine.MAX_ROUNDS
    engine.MAX_ROUNDS = 1
    try:
        chain = [_node(str(i), "Component") for i in range(5)]
        edges = [_edge(str(i), "reports_to", str(i + 1)) for i in range(4)]
        rule = {"id": "up", "kind": "derive",
                "when": [{"edge": ["x", "reports_to|reports_up_to", "y"]}, {"edge": ["y", "reports_to|reports_up_to", "z"]}],
                "then": {"edge": ["x", "reports_up_to", "z"]}, "why": "x"}
        with pytest.raises(engine.DoesNotConverge):
            engine.run([rule], chain, edges)
    finally:
        engine.MAX_ROUNDS = monkey


def test_explain_walks_from_the_rule_down_to_the_evidence():
    result = engine.run([RISK], NODES, EDGES)
    by_id = {n["id"]: n for n in NODES}
    lines = engine.explain(result, by_id, result["edges"][0])
    assert lines[0].startswith("risk.1 -threatens-> system.pay  (derived by rule risk-reaches-system, depth 1)")
    assert any("risk.1  [Risk] risk.1  source: handbook p.1" in l for l in lines)
    assert any("risk.1 -threatens-> component.api  (asserted)" in l for l in lines)
