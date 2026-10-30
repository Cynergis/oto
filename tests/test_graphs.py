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
        init(root, slug="plan", name="The payments plan", ontology="organization-process")
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
    assert "Process" in attributes["classes"] and "Role" in attributes["classes"] and "Document" in attributes["classes"]
    assert node["source_type"] == "inference" and node["source_doc"] == "project.config.json" and node["sources"] == ["project.config.json"]
    assert node["as_of"] and node["valid_from"] == node["as_of"]


def test_an_empty_project_still_describes_itself_and_a_bare_one_cannot(tmp_path):
    root = str(tmp_path / "empty")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="empty", name="Empty", ontology="agent", empty=True)
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
    assert "Process" in descriptor["classes"] and descriptor["engine"]
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


# ---- near-duplicate descriptors (A4) ----

def _node(slug, label, subject, classes, reach=None):
    return {"id": "graph.%s" % slug, "type": "Graph", "label": label, "status": "current",
            "attributes": {"slug": slug, "subject": subject, "classes": classes, "reach": reach or slug + "-kg"}}


def test_overlaps_name_descriptors_an_agent_could_not_tell_apart():
    claims = ["Policy", "Coverage", "Claim", "Incident", "Vehicle", "Document", "Tool", "Graph"]
    a = _node("policy", "Claims policy", "Claims policy: Motor vehicle claims: policy, coverage, claim, incident, handling.", claims)
    b = _node("policy-2", "Claims policy, the copy", "Claims policy, the copy: Motor vehicle claims: policy, coverage, claim, incident, handling.", claims)
    c = _node("plan", "The payments plan", "The payments plan: Messages tied to the item they are about; what waits for a person.",
              ["WorkItem", "Message", "Person", "Document", "Tool", "Graph"])
    found = graphs.overlaps([a, b, c])
    assert [(f["a"], f["b"]) for f in found] == [("graph.policy", "graph.policy-2")], found
    f = found[0]
    assert f["similarity"] >= graphs.NEAR_DUPLICATE and "Claim" in f["shared_classes"] and "Document" not in f["shared_classes"], "the core three every graph has say nothing"
    assert "copy" in f["only_b"] and f["only_a"] == [], "what tells them apart is named: nothing on one side, one word on the other"
    assert "told apart only by" in f["message"] and "graph.policy-2" in f["message"]
    same_reach = graphs.overlaps([a, dict(c, attributes=dict(c["attributes"], reach=a["attributes"]["reach"]))])
    assert len(same_reach) == 1 and "same reach" in same_reach[0]["message"], "two descriptors reached at one place are one graph twice"
    assert graphs.overlaps([a, c]) == [] and graphs.overlaps([a]) == []
    gone = dict(b, status="superseded")
    assert graphs.overlaps([a, gone]) == [], "a superseded descriptor is history, not a duplicate"


def test_ontology_check_warns_on_near_duplicates_and_depend_warns_when_declaring_one(plan, tmp_path):
    for slug, name in (("policy", "Claims policy"), ("policy-2", "Claims policy, the copy")):
        other = str(tmp_path / slug)
        with contextlib.redirect_stdout(io.StringIO()):
            init(other, slug=slug, name=name, ontology="auto-claims")
        code, out = _cli("graph", "describe", "--reach", "https://kg.example.org/" + slug, "--project", other)
        assert code == 0, out
        path = str(tmp_path / (slug + ".json"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        code, out = _cli("graph", "depend", "--on", path, "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", plan)
        assert code == 0, out
        if slug == "policy":
            assert "near-duplicate" not in out
        else:
            assert "near-duplicate" in out and "graph.policy" in out and "told apart only by" in out, "warned at authoring, when the second one is declared"
    code, out = _cli("ontology", "check", "--project", plan)
    assert code == 0, out
    assert "graphs: 3 descriptor(s); 1 near-duplicate pair(s)" in out and "graph.policy ~ graph.policy-2" in out, out
    assert "[advisory]" in out
    code, out = _cli("ontology", "check", "--strict", "--project", plan)
    assert code == 0, "a warning, never an error: both are still reached at runtime"
    code, out = _cli("build", "--project", plan)
    assert code == 0, out


def test_describe_takes_a_subject_so_a_near_duplicate_can_be_sharpened(plan):
    code, out = _cli("graph", "describe", "--subject", "The payments plan: settlement work and who waits on it", "--project", plan)
    assert code == 0 and json.loads(out)["subject"] == "The payments plan: settlement work and who waits on it", out
