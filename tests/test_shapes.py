"""Shapes: constraints declared beside the terms (a relation's min and max, an attribute's required,
a class's requires), evaluated in the engine, blocking in `oto curate check`, held against an
ontology's sample, written as SHACL and read back."""
import json
import os
import tempfile

from oto.builder import build
from oto.cli import main
from oto.curate import session
from oto.model import vocabulary as _vocab
from oto.project import Project
from oto.reason import shapes
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(REPO, "oto", "ontologies", "auto-claims")


def _vocabulary():
    with open(os.path.join(ARCH, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _sample():
    with open(os.path.join(ARCH, "sample.graph.json"), encoding="utf-8") as f:
        return json.load(f)


def test_the_shipped_claims_vocabulary_declares_shapes_its_sample_satisfies():
    vocabulary, sample = _vocabulary(), _sample()
    rows = shapes.declared(vocabulary)
    assert {"kind": "min", "class": "Claim", "subject": "claims_under", "count": 1} in rows
    assert {"kind": "max", "class": "Claim", "subject": "claims_under", "count": 1} in rows
    assert {"kind": "required", "class": "Claim", "subject": "claim_number"} in rows
    assert shapes.problems(vocabulary) == []
    assert shapes.findings(vocabulary, sample["nodes"], sample["edges"]) == []


def test_findings_name_the_node_the_constraint_and_what_was_declared():
    vocabulary, sample = _vocabulary(), _sample()
    stamp = {"status": "current", "attributes": {}}
    nodes = sample["nodes"] + [dict(id="claim.c-9", type="Claim", label="Nine", **stamp)]
    edges = sample["edges"] + [{"from": "payment.indemnity.c-5001", "rel": "charged_to", "to": "coverage.collision"},
                               {"from": "payment.indemnity.c-5001", "rel": "charged_to", "to": "coverage.other"}]
    nodes.append(dict(id="coverage.other", type="Coverage", label="Other", **stamp))
    found = shapes.findings(vocabulary, nodes, edges)
    messages = [f["message"] for f in found]
    assert "Claim claim.c-9 has no claim_number; every Claim must" in messages
    assert "Claim claim.c-9 has 0 claims_under; at least 1 declared" in messages
    assert "Payment payment.indemnity.c-5001 has 3 charged_to; at most 1 declared" in messages
    assert all(f["node"] in ("claim.c-9", "payment.indemnity.c-5001") for f in found)
    # a superseded node constrains nothing
    retired = [dict(n, status="superseded") if n["id"] == "claim.c-9" else n for n in nodes]
    assert not any(f["node"] == "claim.c-9" for f in shapes.findings(vocabulary, retired, edges))
    text = shapes.findings_text(found)
    assert text.startswith("shapes: %d violation(s):" % len(found)) and "[max     ] Payment" in text
    assert shapes.findings_text([]) == "shapes: every node satisfies the declared constraints"


def test_requires_covers_the_kinds_of_a_class_and_a_bad_requires_is_a_problem():
    vocabulary = {"classes": {"Asset": {"definition": "a", "requires": ["owned_by"]},
                              "Component": {"definition": "c", "subclass_of": ["Asset"], "requires": ["serial"]},
                              "Team": {"definition": "t"}},
                  "properties": {"owned_by": {"domain": "Asset", "range": "Team", "definition": "o"},
                                 "part_of": {"range": "Asset", "definition": "p", "min": 1}},
                  "attributes": {"Component": {"serial": {"type": "string", "definition": "s"}}}}
    assert shapes.problems(vocabulary) == ["relation 'part_of' declares min or max but no domain: a count needs a subject class"]
    del vocabulary["properties"]["part_of"]
    vocabulary["classes"]["Team"]["requires"] = ["nope"]
    assert shapes.problems(vocabulary) == ["class 'Team' requires 'nope', which is neither an attribute it declares nor a relation"]
    del vocabulary["classes"]["Team"]["requires"]
    nodes = [dict(id="c.1", type="Component", label="C", status="current", attributes={}),
             dict(id="t.1", type="Team", label="T", status="current", attributes={})]
    found = shapes.findings(vocabulary, nodes, [])
    assert [(f["kind"], f["subject"]) for f in found] == [("requires", "serial"), ("requires", "owned_by")]
    assert found[1]["message"] == "Component c.1 carries no owned_by; every Asset requires it"
    found = shapes.findings(vocabulary, [dict(nodes[0], attributes={"serial": "x"}), nodes[1]],
                            [{"from": "c.1", "rel": "owned_by", "to": "t.1"}])
    assert found == []
    # the shape keys are checked for their form
    assert _vocab.shape_problems({"classes": {"A": {"definition": "a", "requires": "owned_by"}}}) == \
        ["class 'A': `requires` must be a list of attribute or relation names"]
    assert _vocab.shape_problems({"properties": {"p": {"definition": "p", "min": 2, "max": 1}}}) == ["relation 'p': `max` is below `min`"]
    assert _vocab.shape_problems({"attributes": {"A": {"x": {"type": "string", "definition": "x", "required": "yes"}}}}) == \
        ["attribute A.x: `required` must be true or false"]


def test_a_policy_rule_names_the_question_it_protects():
    from oto.reason import rules as _rules
    vocabulary = _vocabulary()
    rule = {"id": "r", "kind": "policy", "why": "because the documents keep raising it", "severity": "warn",
            "when": [{"node": "c", "type": "Claim"}], "then": {"flag": "x"}, "answers": "AC1"}
    assert _rules.problems([rule], vocabulary) == []
    assert _rules.problems([dict(rule, answers="")], vocabulary) == ["rule 'r': `answers` names the question a policy protects, as its id"]
    assert shapes.rule_question_problems([rule], {"AC1": {}}) == []
    assert shapes.rule_question_problems([rule], {"AC2": {}}) == ["rule 'r' answers 'AC1', which questions.json does not declare"]


def test_tightening_a_shape_is_breaking_and_loosening_is_additive():
    old = _vocab.Vocabulary.from_config(_vocabulary())
    config = _vocabulary()
    config["properties"]["claims_under"]["max"] = 2                   # loosened
    config["properties"]["filed_by"]["min"] = 1                       # tightened
    config["attributes"]["Claim"]["claim_number"].pop("required")     # loosened
    config["attributes"]["Policy"]["policy_number"]["required"] = True
    config["classes"]["Claim"]["requires"] = ["arises_from"]          # tightened
    new = _vocab.Vocabulary.from_config(config)
    changes = {(c.kind, c.subject): c for c in _vocab.diff(old, new)}
    assert changes[("cardinality loosened", "claims_under")].severity == _vocab.Change.ADDITIVE
    assert changes[("cardinality tightened", "filed_by")].severity == _vocab.Change.BREAKING and changes[("cardinality tightened", "filed_by")].detail == "0..1 -> 1..1"
    assert changes[("attribute optional", "Claim.claim_number")].severity == _vocab.Change.ADDITIVE
    assert changes[("class requires more", "Claim")].severity == _vocab.Change.BREAKING
    assert ("attribute required", "Policy.policy_number") not in changes, "it was required already"


def test_curate_check_blocks_a_candidate_that_breaks_a_shape_or_leaves_a_required_question_unanswered(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Claims", ontology="auto-claims")
        project = Project.standard(root)
        session.start(project)
        candidate = session.candidate(project)
        candidate["nodes"].append(dict(id="claim.c-9", type="Claim", label="Claim C-9", aliases=[], summary="A second claim.",
                                       attributes={"state": "open"}, tags=[], as_of="2026-09-01", valid_from="2026-09-01",
                                       source_doc="handbook", status="current", sources=["handbook"],
                                       evidence=[{"doc": "handbook", "where": "p.1", "quote": "C-9 was opened."}]))
        session._write(session.candidate_path(project), candidate)
        assert main(["curate", "check", "--project", root]) == 1
        out = capsys.readouterr().out
        assert "shape required: Claim claim.c-9 has no claim_number; every Claim must" in out
        assert "shape min: Claim claim.c-9 has 0 claims_under; at least 1 declared" in out
        assert "question AC1 unanswered: What is claim $CLAIM" in out and "the claim names no policy" in out
        assert "blocking problem(s)" in out
        candidate["nodes"][-1]["attributes"]["claim_number"] = "C-9"
        candidate["edges"] += [{"from": "claim.c-9", "rel": "claims_under", "to": "policy.p-1001"},
                               {"from": "claim.c-9", "rel": "claims_against", "to": "coverage.collision"},
                               {"from": "claim.c-9", "rel": "filed_by", "to": "party.policyholder"},
                               {"from": "claim.c-9", "rel": "arises_from", "to": "incident.2026-03-14"}]
        session._write(session.candidate_path(project), candidate)
        assert main(["curate", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "shape " not in out and "question AC" not in out and "ready to apply" in out


def test_ontology_check_prints_the_shapes_and_strict_fails_on_a_violation(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Claims", ontology="auto-claims")
        project = Project.standard(root)
        assert main(["ontology", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "shapes: " in out and "declared (" in out and "every node satisfies them" in out
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        graph["edges"] = [e for e in graph["edges"] if e["rel"] != "claims_under"]
        json.dump(graph, open(project.graph_path, "w", encoding="utf-8"))
        assert main(["ontology", "check", "--project", root, "--strict"]) == 1
        out = capsys.readouterr().out
        assert "1 violation(s) on the live graph:" in out and "[min     ] Claim claim.c-5001 has 0 claims_under; at least 1 declared" in out


def test_the_turtle_carries_the_shapes_as_shacl_and_the_importer_reads_them_back():
    import pytest
    from oto.model import rdf_import
    if not rdf_import.available():
        pytest.skip("needs rdflib (the `rdf` extra)")
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Claims", ontology="auto-claims")
        project = Project.standard(root)
        build(project)
        ttl = open(os.path.join(project.layout.ontology, "claims.ttl"), encoding="utf-8").read()
        assert "claims:ClaimShape a sh:NodeShape ; sh:targetClass auto-claims:Claim ;" in ttl, "the shape is the project's; the class keeps its IRI"
        assert "sh:path auto-claims:claims_under ; sh:minCount 1 ; sh:maxCount 1 ; sh:message \"a Claim has exactly 1 claims_under\"@en" in ttl
        assert "sh:path auto-claims:claim_number ; sh:minCount 1 ; sh:message \"every Claim has claim_number\"@en" in ttl
        classes, properties, notes = rdf_import.read(os.path.join(project.layout.ontology, "claims.ttl"))
        assert notes == []
        config = json.load(open(project.ontology_config_path, encoding="utf-8"))
        assert properties["claims_under"].get("min") == 1 and properties["claims_under"].get("max") == 1
        assert rdf_import.read.attributes["Claim"]["claim_number"].get("required") is True
        for name, spec in config["properties"].items():
            assert (spec.get("min"), spec.get("max")) == (properties[name].get("min"), properties[name].get("max")), name
        # pyshacl, when installed, agrees with the engine on the exported graph
        try:
            import pyshacl  # noqa: F401
        except ImportError:
            pytest.skip("pyshacl not installed")
        from rdflib import Graph
        data = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        shapes_graph = Graph().parse(os.path.join(project.layout.ontology, "claims.ttl"), format="turtle")
        conforms, _report, _text = pyshacl.validate(data, shacl_graph=shapes_graph, ont_graph=shapes_graph)
        assert conforms
        # and disagrees where the engine does: the same nodes, the same paths
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        graph["nodes"].append(dict(id="claim.c-9", type="Claim", label="Claim C-9", aliases=[], summary="Bare.", attributes={"state": "open"},
                                   tags=[], as_of="2026-09-01", valid_from="2026-09-01", source_doc="handbook", status="current", sources=["handbook"]))
        json.dump(graph, open(project.graph_path, "w", encoding="utf-8"))
        build(project)
        engine_found = {(f["node"], f["subject"]) for f in shapes.findings(config, graph["nodes"], graph["edges"])}
        assert engine_found == {("claim.c-9", "claim_number"), ("claim.c-9", "claims_under"), ("claim.c-9", "arises_from")}
        data = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        conforms, report, _text = pyshacl.validate(data, shacl_graph=shapes_graph, ont_graph=shapes_graph)
        assert not conforms
        from rdflib.namespace import Namespace
        SH = Namespace("http://www.w3.org/ns/shacl#")
        shacl_found = {(str(report.value(r, SH.focusNode)).rsplit("/", 1)[-1], str(report.value(r, SH.resultPath)).rsplit("#", 1)[-1].rsplit("/", 1)[-1])
                       for r in report.subjects(SH.resultPath, None)}
        assert shacl_found == engine_found, "the SHACL rendering and the engine must find the same violations"


def test_a_policy_rule_is_a_shacl_sparql_constraint_that_finds_what_the_engine_finds():
    import pytest
    from oto.model import rdf_import
    if not rdf_import.available():
        pytest.skip("needs rdflib (the `rdf` extra)")
    try:
        import pyshacl
    except ImportError:
        pytest.skip("pyshacl not installed")
    from rdflib import Graph
    from rdflib.namespace import Namespace
    from oto.reason import engine as _engine, rules as _rules
    from oto.model.vocabulary import covers
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="arch", name="Arch", ontology="software-architecture")
        project = Project.standard(root)
        build(project)
        ttl = open(os.path.join(project.layout.ontology, "arch.ttl"), encoding="utf-8").read()
        assert "arch:decision_is_documentedPolicy a sh:NodeShape ; sh:targetClass product:Decision ; sh:severity sh:Warning ; sh:sparql [" in ttl
        assert 'sh:message "a decision must cite the document that records it (answers PR19)"@en' in ttl
        assert "SELECT $this WHERE {" in ttl and 'FILTER(?this_status NOT IN ("current", "intended"))' in ttl, "a policy sees intended facts"
        config = json.load(open(project.ontology_config_path, encoding="utf-8"))
        graph = json.load(open(os.path.join(project.layout.graph, "knowledge-graph.json"), encoding="utf-8"))
        outcome = _engine.run(_rules.load(project), graph["nodes"], graph["edges"], covers=covers(config["classes"]))
        engine_found = {(f["rule"], f["node"]) for f in outcome["findings"]}
        assert engine_found == {("decision-is-documented", "decision.single-ledger")}
        SH = Namespace("http://www.w3.org/ns/shacl#")
        data = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        shapes_graph = Graph().parse(os.path.join(project.layout.ontology, "arch.ttl"), format="turtle")
        conforms, report, _text = pyshacl.validate(data, shacl_graph=shapes_graph, ont_graph=shapes_graph)
        results = [(str(report.value(r, SH.sourceShape)).rsplit("/", 1)[-1], str(report.value(r, SH.focusNode)).rsplit("/", 1)[-1],
                    str(report.value(r, SH.resultSeverity)).rsplit("#", 1)[-1]) for r in report.subjects(SH.focusNode, None)]
        assert results == [("decision_is_documentedPolicy", "decision.single-ledger", "Warning")]


def test_an_ontology_whose_sample_breaks_its_shapes_is_not_usable(monkeypatch):
    from oto.model import ontologies
    from test_ontology_contract import write_ontology, _node
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, root)
        write_ontology(root, "strict", {"Claim": {"definition": "a claim", "requires": ["about"]}, "Doc": {"definition": "d"}},
                       {"about": {"domain": "Claim", "range": "Doc", "definition": "about", "max": 1}},
                       {"nodes": [_node("claim.1", "Claim", "One"), _node("doc.1", "Doc", "D")], "edges": []}, temporal=False)
        problems = ontologies.self_check("strict")
        assert "the sample breaks a declared shape: Claim claim.1 carries no about; every Claim requires it" in problems
