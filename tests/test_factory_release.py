"""The factory plugin's last cut of phase 5 (roadmap J3, J5, J6, J7).

The spec-context skill makes the runner start from graph context: the spec `oto factory spec`
projects, the criteria `oto factory criteria` draws, the context's own questions and `arch_context`,
never loose files. The GitHub Actions path runs the same plugin, so the same hooks, as local
Claude Code, and keeps the run graph as a CI artifact. Metrics are queries over the run graph:
iterations to pass, escalation rate, evaluator-versus-tests disagreement; cost is not the hooks'
to know. The plugin is released as 0.3.0 in the marketplace beside the engine, and the work pack
lets a named person decide a milestone reached, which is how phase 5 is recorded on the roadmap."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys

import pytest

from oto.cli import main
from oto.model import ontologies
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "factory")
LOOP = os.path.join(PLUGIN, "hooks", "loop.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _known_commands():
    import argparse
    from oto.cli import COMMANDS
    known = {}
    for module in COMMANDS:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        module.register(sub)
        for name, p in sub.choices.items():
            choices = []
            for action in p._actions:
                if action.choices and not action.option_strings:
                    choices = list(action.choices)
            known[name] = choices
    return known


# ---- J3: the spec-context skill ----

def test_the_spec_context_skill_starts_the_runner_from_the_graph():
    path = os.path.join(PLUGIN, "skills", "spec-context", "SKILL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("---\nname: spec-context\n")
    for needed in ("oto factory spec", "oto factory criteria", "oto factory scope", "arch_context", "DD22", "AR10", "AR4", ".factory/run.json", "criteria.md"):
        assert needed in text, needed
    assert "loose files" in text and "never" in text
    known = _known_commands()
    for command, subcommand in set(re.findall(r"`oto ([a-z]+) ([a-z-]+)", text)):
        assert command in known, "the skill names `oto %s`, which the engine does not have" % command
        if known[command]:
            assert subcommand in known[command] or subcommand.startswith("-"), "the skill names `oto %s %s`" % (command, subcommand)
    with open(os.path.join(PLUGIN, "agents", "runner.md"), encoding="utf-8") as f:
        runner = f.read()
    assert "spec-context" in runner, "the runner loads the skill before it edits"


# ---- J5: the Actions path, the same hooks ----

def test_the_actions_workflow_runs_the_same_plugin_and_keeps_the_run_graph():
    path = os.path.join(PLUGIN, "workflows", "oto-factory.yml")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("name: oto factory")
    assert "workflow_dispatch" in text and "component:" in text and "cap:" in text
    assert "anthropics/claude-code-action@v1" in text and "oto-factory@" in text and "plugin_marketplaces" in text, "the same plugin, so the same hooks"
    assert "oto factory spec" in text and "oto factory scope" in text and "oto factory criteria" in text and "oto factory run start" in text and "oto factory run sync" in text
    assert "upload-artifact" in text and "runs" in text, "the run graph is the CI audit trail"
    assert "ANTHROPIC_API_KEY" in text and "--max-turns" in text
    assert "spec-context" in text, "the prompt loads the skill"
    with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "workflows/oto-factory.yml" in readme and "same hooks" in readme


# ---- J6: metrics from the run graph ----

@pytest.fixture
def runs(tmp_path):
    root = str(tmp_path / "domain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="domain", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    plan = str(tmp_path / "plan.json")
    code, out = _cli("factory", "plan", "--all", "--json", "--out", plan, "--project", root)
    assert code == 0, out
    runs_dir = str(tmp_path / "runs")
    for run_id in ("r-101", "r-102"):
        code, out = _cli("factory", "run", "start", "--plan", plan, "--at", "2026-10-27", "--id", run_id, "--runs", runs_dir)
        assert code == 0, out
    r1 = os.path.join(runs_dir, "r-101")
    for n, verdict, tests in ((1, "pending", "unknown"), (2, "fail", "pass"), (3, "pass", "pass")):
        code, out = _cli("factory", "run", "record", "--run", r1, "--component", "component.invoice-intake", "--iteration", str(n), "--verdict", verdict, "--tests", tests,
                         "--gap", "g", "--at", "2026-10-27T1%d:00:00Z" % n)
        assert code == 0, out
    for n, verdict, tests in ((1, "pending", "unknown"), (2, "fail", "fail"), (3, "escalated", "fail")):
        code, out = _cli("factory", "run", "record", "--run", r1, "--component", "component.payment-scheduler", "--iteration", str(n), "--verdict", verdict, "--tests", tests, "--at", "2026-10-27T1%d:00:00Z" % n)
        assert code == 0, out
    code, out = _cli("factory", "run", "record", "--run", r1, "--component", "component.approval-policy", "--iteration", "1", "--verdict", "pass", "--tests", "fail", "--at", "2026-10-27T14:00:00Z")
    assert code == 0, out
    r2 = os.path.join(runs_dir, "r-102")
    code, out = _cli("factory", "run", "record", "--run", r2, "--component", "component.invoice-intake", "--iteration", "1", "--verdict", "pass", "--tests", "pass", "--at", "2026-10-28T10:00:00Z")
    assert code == 0, out
    return root, runs_dir


def test_metrics_are_queries_over_the_run_graph(runs):
    root, runs_dir = runs
    r1 = os.path.join(runs_dir, "r-101")
    code, out = _cli("factory", "run", "metrics", "--run", r1)
    assert code == 0, out
    assert "iterations to pass" in out and "escalation rate" in out and "disagree" in out and "cost" in out, out
    code, out = _cli("factory", "run", "metrics", "--run", r1, "--json")
    assert code == 0, out
    m = json.loads(out)
    assert m["runs"] == 1 and m["builds"] == 3 and m["passed"] == 2 and m["escalated"] == 1 and m["planned"] == 0
    assert m["iterations_to_pass"] == {"mean": 2.0, "min": 1, "max": 3, "builds": 2}, m["iterations_to_pass"]
    assert m["escalation_rate"] == pytest.approx(1 / 3)
    assert m["disagreements"] == 2 and {d["build"] for d in m["disagreement_list"]} == {"build.r-101-invoice-intake", "build.r-101-approval-policy"}
    assert m["cost"] == "not recorded by the hooks; the traces of Epic F hold it"
    code, out = _cli("factory", "run", "metrics", "--runs", runs_dir, "--json")
    assert code == 0, out
    m = json.loads(out)
    assert m["runs"] == 2 and m["builds"] == 6 and m["passed"] == 3 and m["planned"] == 2 and m["iterations_to_pass"]["mean"] == pytest.approx(5 / 3)
    code, out = _cli("factory", "run", "metrics", "--runs", str(runs_dir) + "-nowhere")
    assert code == 1 and "nowhere" in out
    code, out = _cli("build", "--project", r1)
    assert code == 0, out
    code, out = _cli("query", "--project", r1, "ask", "FR4", "RUN=run.r-101")
    assert code == 0 and "status: answered" in out and "invoice-intake" in out and "2" in out, "tests passed, the evaluator failed: the second iteration of the intake"
    code, out = _cli("query", "--project", r1, "ask", "FR5", "RUN=run.r-101")
    assert code == 0 and "status: answered" in out and "approval-policy" in out, "tests failed, the evaluator passed"
    config, _sample, _readme = ontologies.load("factory-run")
    assert config["attributes"]["Iteration"]["tests"]["type"] == "enum:pass|fail|unknown" and config["attributes"]["Iteration"]["tests"]["default"] == "unknown"
    assert ontologies.manifest_for("factory-run")["release"] == 2


def test_the_loop_hook_carries_the_test_result_into_the_events(tmp_path):
    cwd = str(tmp_path)
    os.makedirs(os.path.join(cwd, ".factory"))
    with open(os.path.join(cwd, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump({"component": "component.x", "label": "X", "write_scope": ["src"], "read_only": ["contracts"], "cap": 3, "iteration": 0, "run": "r-1"}, f)
    with open(os.path.join(cwd, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "fail", "gaps": ["g"], "tests": "pass"}, f)
    done = subprocess.run([sys.executable, "-I", LOOP], input=json.dumps({"cwd": cwd, "stop_hook_active": True}), cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0 and "block" in done.stdout
    events = [json.loads(l) for l in open(os.path.join(cwd, ".factory", "events.jsonl"), encoding="utf-8") if l.strip()]
    assert events[-1]["tests"] == "pass" and events[-1]["verdict"] == "fail", "the evaluator says what the tests said, so a disagreement is a fact"


# ---- J7: the release, and the phase's milestone ----

def test_the_plugin_is_released_and_a_milestone_is_a_person_s_decision():
    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        plugin = json.load(f)
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
        listed = {p["name"]: p for p in json.load(f)["plugins"]}
    assert plugin["version"] == "0.3.0" and listed["oto-factory"]["version"] == "0.3.0"
    with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "## Releases" in readme and "0.3.0" in readme and "0.2.0" in readme
    config, _sample, _readme = ontologies.load("work")
    state = config["attributes"]["Milestone"]["state"]
    assert state.get("decision") is True and state["default"] == "planned", "a milestone reached is a person's call, recorded as their assertion"
    assert ontologies.manifest_for("work")["release"] == 6 and ontologies.self_check("work") == []
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        milestones = {n["id"]: n for n in json.load(f)["nodes"] if n["type"] == "Milestone"}
    assert milestones["milestone.phase-5"]["attributes"]["state"] == "reached" and any(str(s).startswith("assertion:") for s in milestones["milestone.phase-5"]["sources"])
    assert milestones["milestone.phase-6"]["attributes"]["state"] == "reached" and any(str(s).startswith("assertion:") for s in milestones["milestone.phase-6"]["sources"]), \
        "phase 6 closed the same way: a named person decided it (roadmap PR 8 of phase 6)"
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "spec-context" in text and "oto factory run metrics" in text and "workflows/oto-factory.yml" in text
