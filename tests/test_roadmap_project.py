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

from oto import snapshot, work as _work
from oto.cli import main
from oto.project import Project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADMAP = os.path.join(ROOT, "roadmap")
EPICS = "ABCDEFGHIJKLMN"
SHIPPED = {"b": "Cynergis/oto#56", "k": "Cynergis/oto#57", "l": "Cynergis/oto#54", "m": "Cynergis/oto#58", "n": "Cynergis/oto#60"}


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
