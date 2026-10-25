"""Graph descriptors (roadmap A1, A2): every graph holds one node about itself, a `Graph` of the core
ontology with its subject, main classes, how to reach it and its slug, written by `oto init`; a
dependency on another graph is that graph's descriptor added here, with a `depends_on_graph` edge, so
an agent can list a graph's dependencies, read what each holds and choose which to ask (CORE4)."""
import contextlib
import io
import json
import os

import pytest

from oto import graphs
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def plan(tmp_path):
    root = str(tmp_path / "plan")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plan", name="The payments plan", ontology="communication")
    return root


def _descriptor(root):
    graph = session.live(Project.standard(root))
    found = [n for n in graph["nodes"] if n["type"] == "Graph"]
    return found, graph


def test_init_writes_the_graph_s_own_descriptor(plan):
    found, _graph = _descriptor(plan)
    own = [n for n in found if n["id"] == "graph.plan"]
    assert len(own) == 1, [n["id"] for n in found]
    node = own[0]
    assert node["label"] == "The payments plan" and node["status"] == "current"
    attributes = node["attributes"]
    assert attributes["slug"] == "plan" and attributes["reach"] == "plan-kg" and attributes["subject"]
    assert "WorkItem" in attributes["classes"] and "Message" in attributes["classes"] and "Document" in attributes["classes"]
    assert node["source_type"] == "inference" and node["source_doc"] == "project.config.json" and node["sources"] == ["project.config.json"]
    assert node["as_of"] and node["valid_from"] == node["as_of"]


def test_an_empty_project_still_describes_itself_and_a_bare_one_cannot(tmp_path):
    root = str(tmp_path / "empty")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="empty", name="Empty", ontology="work", empty=True)
    found, graph = _descriptor(root)
    assert [n["id"] for n in found] == ["graph.empty"], "the vocabulary installed, no sample, and the one node every graph holds"
    assert len(graph["nodes"]) == 1
    bare = str(tmp_path / "bare")
    with contextlib.redirect_stdout(io.StringIO()):
        init(bare, slug="bare", name="Bare")
    assert session.live(Project.standard(bare))["nodes"] == [], "no vocabulary declares Graph: nothing is written that the build would refuse"


def test_describe_prints_the_descriptor_another_project_can_depend_on(plan):
    code, out = _cli("graph", "describe", "--project", plan)
    assert code == 0, out
    descriptor = json.loads(out)
    assert descriptor["id"] == "graph.plan" and descriptor["label"] == "The payments plan"
    assert descriptor["subject"] and descriptor["reach"] == "plan-kg" and descriptor["slug"] == "plan"
    assert "WorkItem" in descriptor["classes"] and descriptor["engine"]
    assert set(descriptor) == {"id", "label", "subject", "classes", "reach", "slug", "namespace", "engine", "described_at"}
    code, out = _cli("graph", "describe", "--reach", "https://kg.example.org/plan", "--project", plan)
    assert code == 0 and json.loads(out)["reach"] == "https://kg.example.org/plan", "how the graph is reached from outside, when the server name is not it"


def test_depend_adds_the_other_graph_s_descriptor_and_the_edge_through_the_gates(plan, tmp_path):
    other = str(tmp_path / "policy")
    with contextlib.redirect_stdout(io.StringIO()):
        init(other, slug="policy", name="Policy KB", ontology="auto-claims")
    code, out = _cli("graph", "describe", "--reach", "https://kg.example.org/policy", "--project", other)
    assert code == 0, out
    descriptor_path = str(tmp_path / "policy.descriptor.json")
    with open(descriptor_path, "w", encoding="utf-8") as f:
        f.write(out)
    code, out = _cli("graph", "depend", "--on", descriptor_path, "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", plan)
    assert code == 0, out
    assert "graph.policy" in out and "depends on" in out
    found, graph = _descriptor(plan)
    policy = next(n for n in found if n["id"] == "graph.policy")
    assert policy["attributes"]["reach"] == "https://kg.example.org/policy" and "Claim" in policy["attributes"]["classes"]
    assert policy["source_type"] == "human_assertion" and policy["sources"]
    assert {"from": "graph.plan", "rel": "depends_on_graph", "to": "graph.policy"} in [{k: e[k] for k in ("from", "rel", "to")} for e in graph["edges"]]
    code, out = _cli("graph", "depend", "--on", descriptor_path, "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", plan)
    assert code == 0 and "already" in out, "declared twice is declared once"
    code, out = _cli("build", "--project", plan)
    assert code == 0, out
    code, out = _cli("query", "--project", plan, "ask", "CORE4", "GRAPH=graph.plan")
    assert code == 0 and "status: answered" in out and "Policy KB" in out and "https://kg.example.org/policy" in out, out
    code, out = _cli("graph", "dependencies", "--project", plan)
    assert code == 0 and "graph.policy" in out and "Policy KB" in out and "Claim" in out, out


def test_depend_refuses_what_is_not_a_descriptor_and_a_graph_depending_on_itself(plan, tmp_path):
    bad = str(tmp_path / "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"id": "graph.x", "label": "x"}, f)
    code, out = _cli("graph", "depend", "--on", bad, "--by", "x", "--at", "2026-10-26", "--project", plan)
    assert code == 1 and "subject" in out and "reach" in out, out
    code, out = _cli("graph", "describe", "--project", plan)
    own = str(tmp_path / "own.json")
    with open(own, "w", encoding="utf-8") as f:
        f.write(out)
    code, out = _cli("graph", "depend", "--on", own, "--by", "x", "--at", "2026-10-26", "--project", plan)
    assert code == 1 and "itself" in out, out


def test_a_project_made_before_descriptors_records_its_own_on_request(plan):
    project = Project.standard(plan)
    graph = session.live(project)
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "Graph"]
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    code, out = _cli("graph", "describe", "--record", "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", plan)
    assert code == 0 and "graph.plan" in out and "recorded" in out, out
    found, _graph = _descriptor(plan)
    assert [n["id"] for n in found] == ["graph.plan"]
    code, out = _cli("graph", "describe", "--record", "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", plan)
    assert code == 0 and "already" in out
