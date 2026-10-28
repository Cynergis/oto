"""The roadmap, tracked with the work pack in this repository (`roadmap/`): the first real project of
Epic M and N. It must build clean from what is committed, its states must come from transitions and
events alone, and its published copy must be publishable. If keeping it current is a chore, the
model is wrong, and this test is where that shows first."""
import contextlib
import io
import json
import os
import shutil

import pytest

from oto import audit, snapshot
from oto.packs import work as _work
from oto.cli import main
from oto.project import Project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADMAP = os.path.join(ROOT, "roadmap")
EPICS = "ABCDEFGHIJKLMN"
SHIPPED = {"a": "Cynergis/oto#67", "b": "Cynergis/oto#56", "c": "Cynergis/oto#71", "d": "Cynergis/oto#91", "e": "Cynergis/oto#96", "f": "Cynergis/oto#62", "g": "Cynergis/oto#65", "h": "Cynergis/oto#78", "i": "Cynergis/oto#83", "j": "Cynergis/oto#86", "k": "Cynergis/oto#57", "l": "Cynergis/oto#54", "m": "Cynergis/oto#58", "n": "Cynergis/oto#60"}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def copy(tmp_path):
    """The committed project, built in a scratch copy so the repository stays as it is."""
    root = str(tmp_path / "roadmap")

    def generated(directory, names):
        """Everything under build/ but the corpus, which is an input and is committed."""
        if os.path.abspath(directory) == os.path.join(ROADMAP, "build"):
            return [n for n in names if n != "documents"]
        return [n for n in names if n.endswith(".db") or ".db-" in n]
    shutil.copytree(ROADMAP, root, ignore=generated)
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


def _graph():
    with open(os.path.join(ROADMAP, "graph.json"), encoding="utf-8") as f:
        return json.load(f)


def test_the_project_is_committed_without_build_output_and_on_the_communication_ontology():
    for name in ("project.config.json", "ontology.config.json", "graph.json", "rules.json", "questions.json",
                 "assertions.jsonl", "changelog.jsonl", "README.md"):
        assert os.path.exists(os.path.join(ROADMAP, name)), name
    corpus = os.path.join(ROADMAP, "build", "documents")
    assert os.path.isdir(corpus) and any(f.endswith(".md") for f in os.listdir(corpus)), "the corpus is an input, committed as in repository mode"
    assert os.path.isdir(os.path.join(ROADMAP, "archive")), "the raw document, archived once the graph held its facts"
    with open(os.path.join(ROADMAP, "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["ontology"]["name"] == "communication" and "work" in config["ontology"]["extends"]
    assert "example" not in config["namespace"]
    assert not os.path.exists(os.path.join(ROADMAP, "graph.candidate.json")), "no change left open"
    report = audit.verify(Project.standard(ROADMAP))
    assert report["ok"] and report["records"] >= 1, "the audit log is kept from here on, and its chain holds: %s" % report


def test_the_fourteen_epics_and_six_phases_are_facts_with_their_source_and_no_asserted_state():
    graph = _graph()
    items = {n["id"]: n for n in graph["nodes"] if n["type"] == "WorkItem"}
    assert sorted(items) == ["workitem.epic-%s" % e.lower() for e in EPICS]
    for item in items.values():
        assert "state" not in item["attributes"], "%s writes its state on the item" % item["id"]
        assert item["attributes"]["kind"] == "epic" and item.get("evidence"), item["id"]
    phases = [n for n in graph["nodes"] if n["type"] == "Milestone"]
    assert len(phases) == 6
    scheduled = {e["from"] for e in graph["edges"] if e["rel"] == "scheduled_in" and e["to"] in {p["id"] for p in phases}}
    assert scheduled == set(items), "every epic is in a phase"
    docs = {e["doc"] for n in graph["nodes"] for e in n.get("evidence") or []}
    assert docs and all(os.path.exists(os.path.join(ROADMAP, "build", "documents", d + ".md")) for d in docs), docs


def test_what_shipped_is_deployed_by_the_pull_request_that_merged_it(copy):
    board = _work.board(Project.standard(copy))
    assert board["counts"] == {"open": len(EPICS) - len(SHIPPED), "blocked": 0, "deployed": len(SHIPPED)}
    assert {d["id"]: d["environment"] for d in board["deployed"]} == {"workitem.epic-%s" % e: "prod" for e in SHIPPED}
    graph = _graph()
    for epic, event in SHIPPED.items():
        current = [t for t in _work.transitions_of(graph, "workitem.epic-%s" % epic) if t["status"] == "current"]
        assert len(current) == 1 and current[0]["attributes"]["event"] == "github:" + event, epic
        assert current[0]["source_type"] == "human_assertion" or current[0].get("sources"), "the event is attributed"
    code, out = _cli("query", "--project", copy, "ask", "WK12")
    assert code == 0 and out.count("w.deployed_to=prod") == len(SHIPPED), out
    code, out = _cli("query", "--project", copy, "ask", "WK11")
    assert "status: empty" in out or "(no rows)" in out, out


def test_the_repository_s_decisions_govern_the_epics_they_shaped(copy):
    graph = _graph()
    decisions = {n["id"]: n for n in graph["nodes"] if n["type"] == "Decision"}
    assert set(decisions) >= {"decision.adr-0001", "decision.adr-0002", "decision.adr-0003", "decision.adr-0004", "decision.adr-0005", "decision.adr-0006"}, \
        "the three phase 2 decisions, Cedar, the generated system's IAM and the core-and-packs line, from docs/adr"
    governs = {(e["from"], e["to"]) for e in graph["edges"] if e["rel"] == "governs"}
    assert ("decision.adr-0005", "workitem.epic-e") in governs, "ADR-0005 shaped Epic E's last item, E7"
    for d in decisions.values():
        assert d["attributes"]["status"] == "accepted" and d.get("evidence"), d["id"]
        assert any(e["from"] == d["id"] and e["rel"] == "governs" for e in graph["edges"]), "%s governs something" % d["id"]
    code, out = _cli("query", "--project", copy, "ask", "PR26", "THING=workitem.epic-m")
    assert code == 0 and "status: answered" in out and out.count("d.status=accepted") >= 3, out
    assert "Chiheb Dkhil" in out, "decided by the owner, a person the plan names"


def test_every_phase_is_reached_by_a_person_s_decision():
    """The milestones of phases 1 to 4 closed before a milestone could be decided; once it could, a
    named person recorded each as reached, on the day its last epic was deployed."""
    graph = _graph()
    milestones = {n["id"]: n for n in graph["nodes"] if n["type"] == "Milestone"}
    assert sorted(milestones) == ["milestone.phase-%d" % i for i in range(1, 7)]
    for mid, node in milestones.items():
        assert node["attributes"]["state"] == "reached", mid
        assert any(str(s).startswith("assertion:") for s in node["sources"]), "%s was reached by a person's assertion" % mid
    reached = {}
    with open(os.path.join(ROADMAP, "assertions.jsonl"), encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            for about in record.get("about") or []:
                if about.startswith("milestone.") and "reached" in record.get("text", ""):
                    reached[about] = record
    assert set(reached) == set(milestones)
    assert all(r["by"] == "Chiheb Dkhil" and "decided state of milestone" in r["text"] for r in reached.values())
    assert reached["milestone.phase-1"]["at"] == "2026-10-25" and reached["milestone.phase-4"]["at"] == "2026-10-26"
    assert reached["milestone.phase-5"]["at"] <= reached["milestone.phase-6"]["at"], "in order"


def test_the_roadmap_describes_itself(copy):
    graph = _graph()
    own = [n for n in graph["nodes"] if n["type"] == "Graph" and n["id"] == "graph.oto-roadmap"]
    assert len(own) == 1 and own[0]["attributes"]["reach"] == "oto-roadmap-kg" and "WorkItem" in own[0]["attributes"]["classes"]
    code, out = _cli("query", "--project", copy, "ask", "CORE4", "GRAPH=graph.oto-roadmap")
    assert code == 0 and "status: answered" in out and "oto-roadmap-kg" in out, out
    code, out = _cli("graph", "dependencies", "--project", copy)
    assert code == 0 and "depends on no other graph" in out


def test_the_build_is_clean_and_the_published_copy_is_publishable(copy):
    project = Project.standard(copy)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    graph = _graph()
    assert _work.gates(project, graph, graph, vocabulary) == [], "the committed graph passes its own gates: shapes, blocking policies"
    code, out = _cli("ontology", "check", "--project", copy)
    assert code == 0 and "every node satisfies them" in out, out
    live = snapshot.build(project)
    assert live["work"]["counts"]["deployed"] == len(SHIPPED)
    assert [f for f in live["rules"]["findings"] if f["severity"] == "blocking"] == []
    published = snapshot.published(live)
    assert snapshot.refusals(published) == []
    code, out = _cli("work", "inbox", "--as", "Chiheb Dkhil", "--project", copy)
    assert code == 0 and "nothing pending" in out, out
