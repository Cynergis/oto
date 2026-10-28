"""The run graph and promotion (roadmap Epic I8, J4, M4).

A factory run gets a graph of its own: one OTO project per run, written by the engine from what
the hooks record and never by hand or by a model, holding the plan instance, a `Build` per
component with its state, and every `Iteration` with its verdict and gaps, kept in full so a run
can be replayed. The loop hook appends events to `.factory/events.jsonl`; `oto factory run sync`
reads them into the run graph. Only results are promoted: `oto factory run promote` writes, for a
passed build, a proposal into the main graph (the run as a document, the evaluator's verdict as
evidence of the component, the commit that touches its modules) that goes through the gates like
any other change. A factory verdict updates the work pack: a failed or escalated build blocks the
work item on a named person, with the gaps as the reason (M4)."""
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from oto.packs import factory
from oto.cli import main
from oto.curate import session
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = os.path.join(ROOT, "factory", "hooks", "loop.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _gates(root, proposal, note):
    for step in (("curate", "start"), ("curate", "add", "--from", proposal), ("curate", "check"),
                 ("curate", "apply", "--by", "Sam Lee", "--note", note)):
        code, out = _cli(*step, "--project", root)
        assert code == 0 and "not in the document" not in out and "blocking" not in out.split("gap (")[0], (step, out)
    code, out = _cli("build", "--project", root)
    assert code == 0, out


@pytest.fixture
def domain(tmp_path):
    root = str(tmp_path / "domain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="domain", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


@pytest.fixture
def plan_file(domain, tmp_path):
    path = str(tmp_path / "plan.json")
    code, out = _cli("factory", "plan", "--all", "--json", "--out", path, "--project", domain)
    assert code == 0, out
    return path


# ---- the pack ----

def test_the_run_pack_holds_runs_builds_and_iterations():
    manifest = ontologies.manifest_for("factory-run")
    assert manifest["extends"] == ["oto-core"] and manifest["release"] >= 1 and manifest["domain"] == "software"
    assert ontologies.self_check("factory-run") == [], ontologies.self_check("factory-run")
    config, _sample, readme = ontologies.load("factory-run")
    assert {"Run", "Build", "Iteration"} <= set(config["classes"])
    assert config["attributes"]["Build"]["state"]["type"] == "enum:planned|building|passed|failed|escalated" and config["attributes"]["Build"]["state"]["default"] == "planned"
    assert config["attributes"]["Build"]["component"]["required"] is True and config["attributes"]["Iteration"]["verdict"]["type"] == "enum:pending|pass|fail|escalated"
    assert config["properties"]["build_of"] == dict(config["properties"]["build_of"], domain="Build", range="Run", min=1, max=1)
    assert config["properties"]["iteration_of"] == dict(config["properties"]["iteration_of"], domain="Iteration", range="Build", min=1, max=1)
    questions = ontologies.questions_for("factory-run")
    assert [q for q in questions if q.startswith("FR")] == ["FR1", "FR2", "FR3", "FR4", "FR5"]
    assert "never" in readme and "promot" in readme.lower()
    with open(os.path.join(ROOT, "oto", "ontologies", "product", "ontology.config.json"), encoding="utf-8") as f:
        assert "|run|" in json.load(f)["attributes"]["Document"]["kind"]["type"]


# ---- start, record, replay ----

def test_a_run_starts_from_the_plan_as_a_project_of_its_own(plan_file, tmp_path):
    runs = str(tmp_path / "runs")
    code, out = _cli("factory", "run", "start", "--plan", plan_file, "--at", "2026-10-27", "--id", "r-001", "--runs", runs)
    assert code == 0, out
    run_dir = os.path.join(runs, "r-001")
    assert os.path.isdir(run_dir) and "r-001" in out and "3 build(s)" in out and "1 group(s)" in out, out
    project = Project.standard(run_dir)
    assert project.config()["ontology"]["name"] == "factory-run"
    graph = session.live(project)
    nodes = {n["id"]: n for n in graph["nodes"]}
    run = nodes["run.r-001"]
    assert run["type"] == "Run" and run["attributes"]["started_on"] == "2026-10-27" and run["attributes"]["state"] == "running"
    assert json.loads(run["attributes"]["plan"])["groups"] == [["component.approval-policy", "component.invoice-intake", "component.payment-scheduler"]]
    builds = [n for n in graph["nodes"] if n["type"] == "Build"]
    assert {b["attributes"]["component"] for b in builds} == {"component.approval-policy", "component.invoice-intake", "component.payment-scheduler"}
    assert all(b["attributes"]["state"] == "planned" and b["attributes"]["group"] == 1 for b in builds)
    assert all(("build.r-001-%s" % b["attributes"]["component"].split(".", 1)[1], "build_of", "run.r-001") in {(e["from"], e["rel"], e["to"]) for e in graph["edges"]} for b in builds)
    code, out = _cli("audit", "log", "--project", run_dir)
    assert code == 0 and "factory run start" in out and "oto factory" in out, "the engine writes the run graph; the audit log says so"
    code, out = _cli("audit", "verify", "--project", run_dir)
    assert code == 0, out
    code, out = _cli("factory", "run", "start", "--plan", plan_file, "--at", "2026-10-27", "--id", "r-001", "--runs", runs)
    assert code == 1 and "r-001" in out and "exists" in out, "a run is a partition of its own; it is never overwritten"
    code, out = _cli("factory", "run", "status", "--run", run_dir)
    assert code == 0 and "planned" in out and "Invoice intake" in out and "group 1" in out, out


def test_iterations_are_recorded_in_full_and_a_run_replays(plan_file, tmp_path):
    runs = str(tmp_path / "runs")
    code, out = _cli("factory", "run", "start", "--plan", plan_file, "--at", "2026-10-27", "--id", "r-002", "--runs", runs)
    assert code == 0, out
    run_dir = os.path.join(runs, "r-002")
    code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.invoice-intake", "--iteration", "1", "--verdict", "fail",
                     "--gap", "the IBAN is not validated", "--gap", "no test for a duplicate invoice", "--at", "2026-10-27T10:00:00Z")
    assert code == 0 and "iteration 1" in out and "fail" in out, out
    code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.invoice-intake", "--iteration", "2", "--verdict", "pass", "--at", "2026-10-27T11:00:00Z")
    assert code == 0 and "passed" in out, out
    graph = session.live(Project.standard(run_dir))
    nodes = {n["id"]: n for n in graph["nodes"]}
    build = nodes["build.r-002-invoice-intake"]
    assert build["attributes"]["state"] == "passed" and build["attributes"]["iterations"] == 2
    first = nodes["iteration.r-002-invoice-intake-1"]
    assert first["attributes"] == {"number": 1, "verdict": "fail", "gaps": ["the IBAN is not validated", "no test for a duplicate invoice"], "at": "2026-10-27T10:00:00Z", "tests": "unknown"}
    edges = {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}
    assert ("iteration.r-002-invoice-intake-1", "iteration_of", "build.r-002-invoice-intake") in edges
    assert ("iteration.r-002-invoice-intake-2", "follows", "iteration.r-002-invoice-intake-1") in edges, "the order is a fact, so the run replays"
    code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.invoice-intake", "--iteration", "1", "--verdict", "fail", "--gap", "again", "--at", "2026-10-27T12:00:00Z")
    assert code == 1 and "iteration 1" in out and "recorded" in out, "an iteration is recorded once: the run is kept in full, never rewritten"
    code, out = _cli("factory", "run", "replay", "--run", run_dir, "--component", "component.invoice-intake")
    assert code == 0, out
    assert out.index("iteration 1: fail") < out.index("iteration 2: pass") and "IBAN" in out and "duplicate invoice" in out, out
    code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.payment-scheduler", "--iteration", "3", "--verdict", "escalated", "--gap", "cap reached", "--at", "2026-10-27T13:00:00Z")
    assert code == 0, out
    code, out = _cli("build", "--project", run_dir)
    assert code == 0, out
    code, out = _cli("query", "--project", run_dir, "ask", "FR1", "RUN=run.r-002")
    assert code == 0 and "status: answered" in out and "passed" in out and "escalated" in out and "planned" in out, out
    code, out = _cli("query", "--project", run_dir, "ask", "FR2", "RUN=run.r-002")
    assert code == 0 and "payment-scheduler" in out and "invoice-intake" not in out, "the builds a person must take over"
    code, out = _cli("query", "--project", run_dir, "ask", "FR3", "BUILD=build.r-002-invoice-intake")
    assert code == 0 and "status: answered" in out and "IBAN" in out and out.count("verdict=") == 2, out
    code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.nope", "--iteration", "1", "--verdict", "fail", "--at", "2026-10-27T13:00:00Z")
    assert code == 1 and "component.nope" in out


# ---- the hooks write events; sync reads them into the run graph ----

def _hook(payload, cwd):
    done = subprocess.run([sys.executable, "-I", LOOP], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def test_the_loop_hook_s_events_sync_into_the_run_graph(plan_file, tmp_path):
    runs = str(tmp_path / "runs")
    code, out = _cli("factory", "run", "start", "--plan", plan_file, "--at", "2026-10-27", "--id", "r-003", "--runs", runs)
    assert code == 0, out
    run_dir = os.path.join(runs, "r-003")
    repo = str(tmp_path / "repo")
    os.makedirs(os.path.join(repo, ".factory"))
    with open(os.path.join(repo, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump({"component": "component.invoice-intake", "label": "Invoice intake", "write_scope": ["src/intake"], "read_only": ["contracts"], "cap": 2, "iteration": 0,
                   "run": "r-003"}, f)
    payload = {"cwd": repo, "hook_event_name": "Stop", "stop_hook_active": False}
    code, out, err = _hook(payload, repo)
    assert json.loads(out)["decision"] == "block", out
    with open(os.path.join(repo, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "fail", "gaps": ["the IBAN is not validated"]}, f)
    code, out, err = _hook(dict(payload, stop_hook_active=True), repo)
    assert json.loads(out)["decision"] == "block", out
    code, out, err = _hook(dict(payload, stop_hook_active=True), repo)
    assert "block" not in out and "cap" in out, out
    events_path = os.path.join(repo, ".factory", "events.jsonl")
    assert os.path.exists(events_path), "every decision of the loop is an event"
    events = [json.loads(line) for line in open(events_path, encoding="utf-8") if line.strip()]
    assert [e["event"] for e in events] == ["iteration", "iteration", "escalated"] and events[0]["component"] == "component.invoice-intake" and events[0]["run"] == "r-003"
    assert events[1]["verdict"] == "fail" and events[1]["gaps"] == ["the IBAN is not validated"] and events[0]["verdict"] == "pending"
    assert all(e["at"] for e in events)
    code, out = _cli("factory", "run", "sync", "--run", run_dir, "--events", events_path)
    assert code == 0 and "3 event(s)" in out and "2 iteration(s)" in out and "escalated" in out, out
    graph = session.live(Project.standard(run_dir))
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["build.r-003-invoice-intake"]["attributes"]["state"] == "escalated" and nodes["build.r-003-invoice-intake"]["attributes"]["iterations"] == 2
    assert nodes["iteration.r-003-invoice-intake-1"]["attributes"]["verdict"] == "pending" and nodes["iteration.r-003-invoice-intake-2"]["attributes"]["verdict"] == "fail"
    code, out = _cli("factory", "run", "sync", "--run", run_dir, "--events", events_path)
    assert code == 0 and "0 new" in out, "syncing again adds nothing: every event is recorded once"
    assert sum(1 for n in session.live(Project.standard(run_dir))["nodes"] if n["type"] == "Iteration") == 2
    with open(os.path.join(repo, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "pass", "gaps": []}, f)
    with open(os.path.join(repo, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump({"component": "component.approval-policy", "label": "Approval policy", "write_scope": ["src/policy"], "read_only": ["contracts"], "cap": 3, "iteration": 1, "run": "r-003"}, f)
    code, out, err = _hook(payload, repo)
    assert "passed" in out
    code, out = _cli("factory", "run", "sync", "--run", run_dir, "--events", events_path)
    assert code == 0 and "1 new" in out, out
    assert session.live(Project.standard(run_dir))["nodes"] and {n["id"]: n for n in session.live(Project.standard(run_dir))["nodes"]}["build.r-003-approval-policy"]["attributes"]["state"] == "passed"
    code, out = _cli("factory", "run", "status", "--run", run_dir)
    assert code == 0 and "escalated" in out and "passed" in out and "planned" in out, out
    code, out = _cli("factory", "run", "sync", "--run", run_dir, "--events", str(tmp_path / "nowhere.jsonl"))
    assert code == 1 and "nowhere.jsonl" in out


# ---- promotion into the main graph ----

def test_a_passed_build_s_verdict_and_commit_are_promoted_through_the_gates(domain, plan_file, tmp_path):
    runs = str(tmp_path / "runs")
    code, out = _cli("factory", "run", "start", "--plan", plan_file, "--at", "2026-10-27", "--id", "r-004", "--runs", runs)
    assert code == 0, out
    run_dir = os.path.join(runs, "r-004")
    code, out = _cli("factory", "run", "promote", "--run", run_dir, "--component", "component.invoice-intake", "--commit", "abc1234def5678", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "passed" in out and "planned" in out, "only a passed build is promoted"
    for n, verdict in ((1, "fail"), (2, "pass")):
        code, out = _cli("factory", "run", "record", "--run", run_dir, "--component", "component.invoice-intake", "--iteration", str(n), "--verdict", verdict,
                         "--gap", "x", "--at", "2026-10-27T1%d:00:00Z" % n)
        assert code == 0, out
    code, out = _cli("factory", "run", "promote", "--run", run_dir, "--component", "component.invoice-intake", "--commit", "abc1234def5678", "--at", "2026-10-28", "--into", domain)
    assert code == 0, out
    assert "run-r-004" in out and "proposals/run-r-004-invoice-intake.json" in out and "curate add" in out, out
    text = open(os.path.join(domain, "build", "documents", "run-r-004.md"), encoding="utf-8").read()
    assert text.startswith("# Factory run r-004") and "invoice-intake: passed after 2 iteration(s), commit abc1234def5678" in text
    with open(os.path.join(domain, "proposals", "run-r-004-invoice-intake.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["document.run-r-004"]["attributes"] == {"kind": "run"}
    evidence = nodes["evidence.run-r-004-invoice-intake"]
    assert evidence["type"] == "Evidence" and evidence["attributes"] == {"kind": "review", "value": "pass after 2 iteration(s)", "observed_on": "2026-10-28", "source_url": "run r-004"}
    assert nodes["commit.abc1234def56"]["type"] == "Commit" and nodes["commit.abc1234def56"]["attributes"]["sha"] == "abc1234def5678"
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("evidence.run-r-004-invoice-intake", "evidence_of", "component.invoice-intake") in edges
    assert ("commit.abc1234def56", "touches", "codemodule.src-intake") in edges, "the commit touches the modules that implement the component"
    assert not any(n["type"] in ("Build", "Iteration", "Run") for n in proposal["nodes"]), "run state stays in the run graph; only the result is promoted"
    _gates(domain, os.path.join(domain, "proposals", "run-r-004-invoice-intake.json"), "promoted from run r-004")
    code, out = _cli("query", "--project", domain, "ask", "AR5", "NODE=component.invoice-intake")
    assert code == 0 and "abc1234def5678" in out, "the promoted commit is the module's latest"
    code, out = _cli("ontology", "check", "--project", domain)
    assert code == 0 and "every node satisfies them" in out, out
    code, out = _cli("factory", "run", "promote", "--run", run_dir, "--component", "component.nope", "--commit", "abc", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "component.nope" in out
    code, out = _cli("factory", "run", "promote", "--run", run_dir, "--component", "component.invoice-intake", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "--commit" in out


# ---- M4: a verdict updates the work item ----

def test_a_failed_or_escalated_build_blocks_the_work_item_on_a_person(tmp_path):
    root = str(tmp_path / "work")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="work", name="The plan", ontology="work")
    code, out = _cli("work", "event", "verdict", "--item", "workitem.e-checkout", "--run", "r-005", "--component", "component.payment-api", "--verdict", "pass",
                     "--at", "2026-10-28", "--by", "oto factory", "--project", root)
    assert code == 0 and "noted" in out and "nothing appended" in out, "a pass changes no state: deployed is set by a merge or a promotion"
    code, out = _cli("work", "event", "verdict", "--item", "workitem.e-checkout", "--run", "r-005", "--component", "component.payment-api", "--verdict", "fail",
                     "--gap", "the IBAN is not validated", "--waiting-on", "person.m-okafor", "--at", "2026-10-28", "--by", "oto factory", "--project", root)
    assert code == 0 and "blocked" in out and "r-005" in out, out
    code, out = _cli("work", "board", "--project", root)
    assert code == 0 and "blocked (2)" in out and "Checkout payment" in out, "the sample's block, and the factory's"
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    code, out = _cli("query", "--project", root, "ask", "WK11")
    assert code == 0 and "IBAN" in out and "r-005" in out, "the gaps are the reason, the run is named"
    code, out = _cli("work", "event", "verdict", "--item", "workitem.e-checkout", "--run", "r-005", "--component", "component.payment-api", "--verdict", "escalated",
                     "--gap", "cap reached", "--at", "2026-10-29", "--by", "oto factory", "--project", root)
    assert code == 1 and "--waiting-on" in out, "a block names whom it waits on"
    code, out = _cli("work", "event", "verdict", "--item", "workitem.e-checkout", "--run", "r-005", "--component", "component.payment-api", "--verdict", "maybe",
                     "--at", "2026-10-29", "--by", "oto factory", "--project", root)
    assert code == 1 and "pass" in out and "fail" in out and "escalated" in out


def test_the_docs_name_the_run_graph():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto factory run" in text and "events.jsonl" in text and "work event verdict" in text
    with open(os.path.join(ROOT, "factory", "README.md"), encoding="utf-8") as f:
        assert "oto factory run sync" in f.read()
