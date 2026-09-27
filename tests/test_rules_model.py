"""A rule set is vocabulary: validated before it runs, reasoned about, versioned."""
from oto.reason import rules

VOCAB = {"classes": {"Risk": "r", "Component": "c", "System": "s", "DecisionRecord": "d", "Document": "doc", "Claim": "cl"},
         "properties": {"threatens": ["Risk", "Component|System", None, "x"], "part_of": ["Component", "System", None, "x"],
                        "documented_in": ["DecisionRecord", "Document", None, "x"], "depends_on": ["Component", "Component", None, "x"]},
         "attributes": {"Claim": {"amount": ["number", "x"], "state": ["enum:open|closed", "x"]}}}


def _rule(**over):
    base = {"id": "risk-reaches-system", "kind": "derive",
            "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
            "then": {"edge": ["r", "threatens", "s"]}, "why": "A risk to a part is a risk to the whole."}
    base.update(over)
    return base


def test_a_valid_set_has_no_problems():
    policy = {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
              "when": [{"node": "d", "type": "DecisionRecord"}, {"not_edge": ["d", "documented_in", "*"]}],
              "then": {"flag": "cite the document"}, "why": "A decision nobody can open is a rumour."}
    attr = {"id": "high-value", "kind": "derive",
            "when": [{"node": "c", "type": "Claim", "where": {"state": "open", "amount": {">": 10000}}}],
            "then": {"attribute": ["c", "state", "open"]}, "why": "x"}
    assert rules.problems([_rule(), policy, attr], VOCAB) == []


def test_each_defect_is_named():
    probs = rules.problems([
        _rule(id="a"), _rule(id="a"),
        _rule(id="b", kind="infer"),
        _rule(id="c", why=""),
        _rule(id="d", when=[{"edge": ["r", "menaces", "c"]}]),
        _rule(id="e", when=[{"node": "x", "type": "Ghost"}], then={"edge": ["x", "part_of", "y"]}),
        _rule(id="f", then={"edge": ["r", "threatens", "zz"]}),
        _rule(id="g", when=[{"not_edge": ["r", "threatens", "*"]}]),
        _rule(id="h", then={"flag": "no"}),
        _rule(id="i", kind="policy", severity="fatal", then={"flag": "x"}),
        _rule(id="j", when=[{"node": "c", "type": "Claim", "where": {"state": {">": "open"}}}], then={"attribute": ["c", "state", "x"]}),
        _rule(id="k", when=[{"node": "c", "type": "Claim", "where": {"colour": "red"}}], then={"attribute": ["c", "state", "x"]}),
        _rule(id="l", when=[{"node": "c", "type": "Claim"}], then={"attribute": ["c", "colour", "red"]}),
    ], VOCAB)
    text = "\n".join(probs)
    for expected in ("duplicate id", "kind must be derive or policy", "has no `why`", "relation 'menaces' is not declared",
                     "class 'Ghost' is not declared", "variable 'zz' in `then` is not bound", "not_edge is allowed in policy rules only",
                     "a derive rule's action must be edge or attribute", "severity must be warn or blocking",
                     "'>' on state, which is declared enum:open|closed", "attribute 'colour' is not declared for Claim",
                     "Claim declares its attributes and 'colour' is not one of them"):
        assert expected in text, expected


def test_diff_classifies_added_removed_and_changed():
    old = [_rule(id="a"), _rule(id="b"), _rule(id="c")]
    new = [_rule(id="a"), _rule(id="c", then={"edge": ["r", "threatens", "c"]}), _rule(id="d")]
    assert rules.diff(old, new) == (["d"], ["b"], ["c"])


def test_load_and_save_round_trip(tmp_path):
    import types
    project = types.SimpleNamespace(data=str(tmp_path))
    assert rules.load(project) == []
    rules.save(project, [_rule()])
    assert rules.load(project)[0]["id"] == "risk-reaches-system"
