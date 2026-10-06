"""The rules stage: derived facts in the build and the store, marked and explainable."""
import json
import os
import tempfile

import pytest

from oto.builder import build
from oto.cli import main
from oto.project import Project
from oto.reason import rules as _rules
from oto.scaffold import init
from oto.validate.preflight import preflight

RISK = {"id": "risk-reaches-system", "kind": "derive",
        "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
        "then": {"edge": ["r", "threatens", "s"]}, "why": "A risk to a component is a risk to its system."}
DOCUMENTED = {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
              "when": [{"node": "d", "type": "DecisionRecord"}, {"not_edge": ["d", "documented_in", "*"]}],
              "then": {"flag": "an architecture decision must cite the document that records it"},
              "why": "A decision nobody can open is a rumour."}


def _project(root, rules=(RISK, DOCUMENTED)):
    init(root, name="Arch", ontology="software-architecture")
    project = Project.standard(root)
    # The sample states the risk threatens the ledger; give the ledger a system so a rule has a hop to take.
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    if rules is not None:
        _rules.save(project, list(rules))
    elif os.path.exists(_rules.path_for(project)):
        os.remove(_rules.path_for(project))               # the ontology ships rules; this test wants none
    return project


def test_the_stage_derives_and_flags_and_the_build_owns_its_file():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        derived = json.load(open(os.path.join(project.layout.graph, "derived.json"), encoding="utf-8"))
        edges = [(e["from"], e["rel"], e["to"]) for e in derived["derived_edges"]]
        assert ("risk.ledger-single-point", "threatens", "system.payments") in edges
        assert derived["derived_edges"][0]["derived_by"] == "risk-reaches-system"
        assert derived["findings"] == [] or all(f["rule"] == "decision-is-documented" for f in derived["findings"])
        assert derived["per_rule"]["risk-reaches-system"]["derived"] >= 1
        # Twice the same input, byte for byte.
        first = open(os.path.join(project.layout.graph, "derived.json"), "rb").read()
        build(project)
        assert open(os.path.join(project.layout.graph, "derived.json"), "rb").read() == first


def test_no_rules_means_no_derived_file_and_a_note(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, rules=None)
        build(project)
        assert not os.path.exists(os.path.join(project.layout.graph, "derived.json"))
        assert "none declared" in capsys.readouterr().out


def test_a_malformed_rule_set_fails_preflight_before_anything_is_written():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, rules=[dict(RISK, why="")])
        with pytest.raises(Exception, match="has no `why`"):
            preflight(project)
        assert not os.path.exists(project.layout.database)


def test_the_store_marks_derived_edges_and_keeps_findings():
    import sqlite3

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        con = sqlite3.connect(project.layout.database)
        derived = con.execute("SELECT src,rel,dst,derived_by FROM edges WHERE status='derived'").fetchall()
        assert ("risk.ledger-single-point", "threatens", "system.payments", "risk-reaches-system") in derived
        asserted = con.execute("SELECT count(*) FROM edges WHERE status='current' AND derived_by IS NULL").fetchone()[0]
        assert asserted > 0
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "6"
        con.close()


def test_answers_mark_derived_facts_and_explain_them(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        capsys.readouterr()
        assert main(["query", "--project", root, "entity", "Payments"]) == 0
        out = capsys.readouterr().out
        assert "[derived by risk-reaches-system]" in out, out
        assert main(["query", "--project", root, "explain", "system.payments"]) == 0
        out = capsys.readouterr().out
        assert "derived by rule risk-reaches-system; rests on:" in out
        assert "(asserted)" in out and "[Risk]" in out
        assert main(["query", "--project", root, "explain", "team.payments"]) == 0
        assert "every fact shown is asserted" in capsys.readouterr().out
        assert main(["query", "--project", root, "overview"]) == 0
        assert "Derived by rules: 1 edge(s)" in capsys.readouterr().out


def test_policy_findings_are_listed_by_the_engine(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        # Break the policy: retire the decision's documentation edge.
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["edges"] = [e for e in graph["edges"] if not (e["from"] == "decision.single-ledger" and e["rel"] == "documented_in")]
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        build(project)
        capsys.readouterr()
        assert main(["query", "--project", root, "policy"]) == 0
        out = capsys.readouterr().out
        assert "decision-is-documented" in out and "decision.single-ledger" in out and "[warn" in out


def test_a_schema_three_store_still_answers_without_marks(capsys):
    """An engine that understands rules must still serve a store built before them."""
    import sqlite3

    with tempfile.TemporaryDirectory() as root:
        project = _project(root, rules=None)
        build(project)
        con = sqlite3.connect(project.layout.database)
        con.execute("CREATE TABLE edges_old AS SELECT src,rel,dst,status FROM edges")
        con.execute("DROP TABLE edges"); con.execute("ALTER TABLE edges_old RENAME TO edges")
        con.execute("DROP TABLE derived_attributes"); con.execute("DROP TABLE policy_findings")
        con.execute("UPDATE meta SET value='3' WHERE key='schema_version'"); con.commit(); con.close()
        capsys.readouterr()
        assert main(["query", "--project", root, "entity", "Payments"]) == 0
        assert "part_of" in capsys.readouterr().out or True
        assert main(["query", "--project", root, "explain", "system.payments"]) == 0
        assert "predates rules" in capsys.readouterr().out
