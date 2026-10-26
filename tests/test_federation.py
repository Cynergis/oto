"""Federation (roadmap A3, A5): an agent at a graph lists the graphs it depends on, reads what each
holds, chooses, and asks it. `kg_dependencies` returns the descriptors (ranked for a question when
one is given; two close candidates are both offered, so the model chooses); `kg_call` follows a
dependency's reach over HTTP and returns what that graph answered. A concierge root is a project
that holds nothing but descriptors: every question starts there."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

from test_apps import _engine, _get

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _descriptor_file(root, tmp_path, reach):
    code, out = _cli("graph", "describe", "--reach", reach, "--project", root)
    assert code == 0, out
    path = str(tmp_path / (os.path.basename(root) + ".descriptor.json"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path


def _call(engine, name, **arguments):
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = reply["result"]
    return result["isError"], "".join(c["text"] for c in result["content"])


@pytest.fixture
def world(tmp_path):
    """Two project graphs and a concierge root that depends on both."""
    plan, policy, root = str(tmp_path / "plan"), str(tmp_path / "policy"), str(tmp_path / "root")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plan, slug="plan", name="The payments plan", ontology="communication")
        init(policy, slug="policy", name="Claims policy", ontology="auto-claims")
        init(root, slug="root", name="Concierge", concierge=True)
    for project, reach in ((plan, "http://127.0.0.1:1/plan"), (policy, "http://127.0.0.1:1/policy")):
        code, out = _cli("graph", "depend", "--on", _descriptor_file(project, tmp_path, reach), "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", root)
        assert code == 0, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return {"plan": plan, "policy": policy, "root": root}


def test_a_concierge_root_holds_descriptors_only(world, tmp_path):
    root = world["root"]
    project = Project.standard(root)
    assert project.config()["kind"] == "concierge" and project.config()["ontology"]["name"] == "oto-core"
    graph = session.live(project)
    assert sorted(n["type"] for n in graph["nodes"]) == ["Graph", "Graph", "Graph"]
    assert sorted(e["rel"] for e in graph["edges"]) == ["depends_on_graph", "depends_on_graph"]
    graph["nodes"].append({"id": "doc.stray", "type": "Document", "label": "A stray document", "status": "current",
                           "as_of": "2026-10-26", "valid_from": "2026-10-26", "source_doc": "x", "sources": ["x"], "aliases": [], "tags": []})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    code, out = _cli("build", "--project", root)
    assert code != 0 and "descriptors only" in out and "doc.stray" in out, out


def test_kg_dependencies_lists_what_the_graph_depends_on_and_ranks_them_for_a_question(world):
    engine = _engine(Project.standard(world["root"]))
    error, text = _call(engine, "kg_dependencies")
    assert not error, text
    assert "graph.root" in text and "graph.plan" in text and "graph.policy" in text
    assert "The payments plan" in text and "Claims policy" in text and "http://127.0.0.1:1/policy" in text
    assert "WorkItem" in text and "Claim" in text, "the classes each holds, so an agent can tell them apart"
    error, text = _call(engine, "kg_dependencies", question="which claims cover the vehicle in that incident")
    assert not error and text.index("graph.policy") < text.index("graph.plan"), text
    assert "ask graph.policy" in text
    error, text = _call(engine, "kg_dependencies", question="what is blocked on the settlement work item and who is waiting")
    assert not error and text.index("graph.plan") < text.index("graph.policy"), text
    error, text = _call(engine, "kg_dependencies", question="what documents exist")
    assert not error and "both" in text.lower() or "either" in text.lower(), "two candidates as close as each other are both offered: the model chooses"
    error, text = _call(engine, "kg_dependencies", graph="graph.plan")
    assert not error and "depends on no other graph" in text, text
    error, text = _call(engine, "kg_dependencies", graph="graph.nothing")
    assert error and "graph.nothing" in text


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def served_plan(tmp_path):
    """The payments plan served over HTTP in its own process, so the root can reach it."""
    plan = str(tmp_path / "served")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plan, slug="served", name="The served plan", ontology="communication")
    code, out = _cli("build", "--project", plan)
    assert code == 0, out
    port = _free_port()
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.Popen([sys.executable, "-m", "oto.cli", "serve", "--project", plan, "--http", "127.0.0.1:%d" % port],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = "http://127.0.0.1:%d" % port
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=1):
                break
        except Exception:                                      # noqa: BLE001 - not up yet
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("the served plan did not come up")
    yield plan, url
    proc.kill()
    proc.wait(timeout=10)


def test_kg_call_follows_a_dependency_s_reach_over_http(served_plan, tmp_path):
    plan, url = served_plan
    root = str(tmp_path / "root")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="root", name="Concierge", concierge=True)
    code, out = _cli("graph", "depend", "--on", _descriptor_file(plan, tmp_path, url), "--by", "Chiheb Dkhil", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    engine = _engine(Project.standard(root))
    error, text = _call(engine, "kg_call", graph="graph.served", tool="kg_search", arguments={"query": "settlement", "n": 3})
    assert not error, text
    assert text.startswith("from The served plan (%s)" % url) and "settlement" in text.lower(), text
    error, text = _call(engine, "kg_call", graph="The served plan", tool="kg_entity", arguments={"term": "Daily settlement batch"})
    assert not error and "Daily settlement batch" in text and "WorkItem" in text, text
    error, text = _call(engine, "kg_call", graph="graph.served", tool="kg_call", arguments={})
    assert error and "one hop" in text
    error, text = _call(engine, "kg_call", graph="graph.served", tool="kg_nothing", arguments={})
    assert error and "kg_nothing" in text
    error, text = _call(engine, "kg_call", graph="graph.elsewhere", tool="kg_search", arguments={"query": "x"})
    assert error and "graph.elsewhere" in text
    # the root served over HTTP exposes both as routes
    from oto.serve import http as _http
    server = _http.Server(engine, "127.0.0.1", 0, project_root=root, identity=Project.standard(root).config()).start()
    try:
        status, _c, body = _get(server.url + "/api/dependencies")
        assert status == 200 and "graph.served" in json.loads(body)["text"]
        status, _c, body = _get(server.url + "/api/call?graph=graph.served&tool=kg_search&query=settlement")
        assert status == 200 and "settlement" in json.loads(body)["text"].lower(), body
    finally:
        server.stop()


def test_kg_call_refuses_a_reach_that_is_not_http(world):
    engine = _engine(Project.standard(world["root"]))
    graph = session.live(Project.standard(world["root"]))
    for n in graph["nodes"]:
        if n["id"] == "graph.plan":
            n["attributes"]["reach"] = "plan-kg"
    with open(Project.standard(world["root"]).graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    code, out = _cli("build", "--project", world["root"])
    assert code == 0, out
    engine = _engine(Project.standard(world["root"]))
    error, text = _call(engine, "kg_call", graph="graph.plan", tool="kg_search", arguments={"query": "x"})
    assert error and "plan-kg" in text and "http" in text.lower()
    error, text = _call(engine, "kg_call", graph="graph.policy", tool="kg_search", arguments={"query": "x"})
    assert error and "could not be reached" in text, "a reach nothing listens on is an error in words, not a traceback"
