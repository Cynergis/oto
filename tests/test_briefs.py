"""Briefs: what an agent must know before a task, READY or BLOCKED by name; and the `no_gaps`
gate they lean on (an answer may be empty, a gap makes it unanswered)."""
import json
import os
import subprocess
import sys
import tempfile

from oto.builder import build
from oto.model.vocabulary import covers
from oto.project import Project
from oto.reason import briefs as B, questions as Q
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QUESTIONS = {
    "CQ1": {"who": "an on-call engineer", "question": "Which components make up $SYSTEM, and where does each run?", "why": "w",
            "params": {"SYSTEM": {"type": "System"}},
            "ask": {"when": [{"edge": ["c", "part_of", "$SYSTEM"]}, {"node": "c", "type": "Component"}, {"edge": ["c", "runs_in", "e"]}],
                    "select": ["c.label", "e.label"]},
            "gate": "non_empty", "gaps": {"when": [{"not_edge": ["*", "part_of", "$SYSTEM"]}], "say": "no component is part of the system"}},
    "CQ2": {"who": "an architect", "question": "Which interfaces of $SYSTEM have a URL, and which lack one?", "why": "w",
            "params": {"SYSTEM": {"type": "System"}},
            "ask": {"when": [{"edge": ["i", "part_of", "$SYSTEM"]}, {"node": "i", "type": "Interface", "where": {"url": {"exists": True}}}],
                    "select": ["i.label", "i.url"]},
            "gate": "no_gaps",
            "gaps": {"when": [{"edge": ["i", "part_of", "$SYSTEM"]}, {"node": "i", "type": "Interface", "where": {"url": {"exists": False}}}],
                     "say": "an interface has no URL"}},
    "CQ3": {"who": "a risk owner", "question": "What threatens $SYSTEM?", "why": "w", "params": {"SYSTEM": {"type": "System"}},
            "ask": {"when": [{"edge": ["r", "threatens", "$SYSTEM"]}], "select": ["r.label"]}, "gate": "any"},
}
BRIEFS = {"operate-system": {"description": "An engineer is about to take a system on call.", "params": {"SYSTEM": "System"},
                             "required": ["CQ1", "CQ2"], "optional": ["CQ3"]}}


def _project(root, keep_shipped=False):
    init(root, slug="arch", name="Arch", ontology="software-architecture")
    project = Project.standard(root)
    Q.save(project, dict(Q.load(project), **QUESTIONS) if keep_shipped else QUESTIONS)
    B.save(project, BRIEFS)
    return project


def _query(root, *args):
    r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root] + list(args),
                       cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), capture_output=True, text=True)
    return r.stdout


def test_no_gaps_answers_with_nothing_and_is_unanswered_by_a_gap():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        vocabulary = json.load(open(project.ontology_config_path, encoding="utf-8"))
        cov = covers(vocabulary["classes"])
        graph["edges"].append({"from": "interface.payments-v2", "rel": "part_of", "to": "system.payments"})
        ok = Q.run("CQ2", QUESTIONS["CQ2"], {"SYSTEM": "system.payments"}, graph["nodes"], graph["edges"], cov)
        assert ok["status"] == "answered" and ok["rows"] == [{"i.label": "Payments API v2", "i.url": "https://api.acme.example/payments/v2"}]
        # no interface at all: answered with nothing, not a gap
        bare = Q.run("CQ2", QUESTIONS["CQ2"], {"SYSTEM": "system.payments"}, graph["nodes"],
                     [e for e in graph["edges"] if e["from"] != "interface.payments-v2"], cov)
        assert bare["status"] == "answered" and bare["rows"] == [] and bare["gaps"] == []
        # an interface without a URL: a gap, so unanswered, even beside an answered row
        nodes = graph["nodes"] + [dict(id="interface.bare", type="Interface", label="Bare interface", status="current", attributes={})]
        edges = graph["edges"] + [{"from": "interface.bare", "rel": "part_of", "to": "system.payments"}]
        gap = Q.run("CQ2", QUESTIONS["CQ2"], {"SYSTEM": "system.payments"}, nodes, edges, cov)
        assert gap["status"] == "unanswered" and len(gap["rows"]) == 1 and gap["gaps"] == ["an interface has no URL"]
        assert Q.problems({"X": dict(QUESTIONS["CQ2"], gate="gaps_only")}, vocabulary), "the gate has a name"


def test_a_brief_is_ready_or_blocked_by_name_and_the_table_runs_every_candidate():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        vocabulary = json.load(open(project.ontology_config_path, encoding="utf-8"))
        cov = covers(vocabulary["classes"])
        assert B.problems(BRIEFS, QUESTIONS) == []
        assert any("needs parameter SYSTEM" in p for p in B.problems({"t": {"description": "d", "required": ["CQ1"]}}, QUESTIONS))
        assert any("not declared" in p for p in B.problems({"t": {"description": "d", "params": {"SYSTEM": "System"}, "required": ["CQ9"]}}, QUESTIONS))
        ready = B.run("operate-system", BRIEFS["operate-system"], {"SYSTEM": "system.payments"}, QUESTIONS, graph["nodes"], graph["edges"], cov)
        assert ready["status"] == "READY" and [q["id"] for q in ready["questions"]] == ["CQ1", "CQ2", "CQ3"]
        assert [q["required"] for q in ready["questions"]] == [True, True, False]
        assert "operate-system  SYSTEM=system.payments  ->  READY" in B.text(ready) and "+ CQ1 REQ" in B.text(ready)
        lonely = dict(id="system.lonely", type="System", label="Lonely system", status="current", attributes={})
        blocked = B.run("operate-system", BRIEFS["operate-system"], {"SYSTEM": "system.lonely"}, QUESTIONS,
                        graph["nodes"] + [lonely], graph["edges"], cov)
        assert blocked["status"] == "BLOCKED" and [b["id"] for b in blocked["blocking"]] == ["CQ1"]
        assert blocked["blocking"][0]["gaps"] == ["no component is part of the system"]
        assert "blocked on: CQ1" in B.text(blocked)
        rows = B.table("operate-system", BRIEFS["operate-system"], QUESTIONS, graph["nodes"] + [lonely], graph["edges"], cov)
        assert [(nid, r["status"]) for nid, _l, r in rows] == [("system.lonely", "BLOCKED"), ("system.payments", "READY")]
        assert "1 READY, 1 BLOCKED" in B.table_text(rows)


def test_the_store_carries_the_briefs_and_the_server_and_the_cli_run_them():
    from oto.serve.store import SqliteStore
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        store = SqliteStore(project.layout.database)
        try:
            assert list(store.questions()) == ["CQ1", "CQ2", "CQ3"], "the brief rows are not questions"
            assert list(store.briefs()) == ["operate-system"]
        finally:
            store.close()
        out = _query(root, "brief", "operate-system", "SYSTEM=Payments platform")
        assert "operate-system  SYSTEM=Payments platform  ->  READY" in out and "+ CQ1 REQ" in out and "o CQ3 opt" in out, out
        table = _query(root, "brief", "operate-system")
        assert "system.payments" in table and "1 READY, 0 BLOCKED" in table, table
        assert "No brief 'x'; declared: operate-system" in _query(root, "brief", "x")
        assert "No entity matched 'nothing-xyz' for SYSTEM." in _query(root, "brief", "operate-system", "SYSTEM=nothing-xyz")


def test_a_brief_naming_an_unknown_question_refuses_the_build_and_an_ontology_ships_its_briefs(tmp_path, monkeypatch):
    from oto.model import ontologies
    from oto.project import ProjectError
    import pytest
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path))
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, keep_shipped=True)
        B.save(project, {"t": {"description": "d", "params": {"SYSTEM": "System"}, "required": ["CQ9"]}})
        with pytest.raises(ProjectError) as exc:
            build(project)
        assert "briefs.json is not usable" in str(exc.value) and "CQ9" in str(exc.value)
        B.save(project, BRIEFS)
        _path, problems = ontologies.export(project, "arch-briefs")
        assert problems == [], problems
        assert ontologies.briefs_for("arch-briefs") == BRIEFS
        assert "briefs" in ontologies.manifest_for("arch-briefs")["carries"]
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="b", name="B", ontology="arch-briefs")
        assert B.load(Project.standard(root)) == BRIEFS, "a project started from the ontology gets its briefs"
