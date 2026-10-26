"""The factory plugin on files (roadmap Epic J, J1, J2 and J7 first cut).

A second plugin in this repository, `factory/`, beside the engine's: three agent definitions
(a runner that builds a component inside its write scope, an evaluator that judges the result
from the spec, the criteria, the code and the test output and never from the runner's reasoning,
an aggregator that gathers verdicts), two hooks that are plain Python with no engine needed (a
PreToolUse guard that refuses an edit outside the run's write scope or inside its read-only
paths, a Stop hook that keeps the loop going on the evaluator's gaps and stops it at the
iteration cap), and the packaging that lists it in the marketplace. The run's scope comes from a
snapshot file, `.factory/run.json`, written by `oto factory scope <component>` from the graph's
code map; Epic E replaces the file with a signed policy snapshot."""
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from oto.cli import main
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "factory")
GUARD = os.path.join(PLUGIN, "hooks", "guard.py")
LOOP = os.path.join(PLUGIN, "hooks", "loop.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _hook(script, payload, cwd):
    done = subprocess.run([sys.executable, "-I", script], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def _snapshot(cwd, **more):
    run = {"component": "component.invoice-intake", "label": "Invoice intake", "write_scope": ["src/intake", "tests/intake"], "read_only": ["contracts"],
           "cap": 3, "iteration": 0, "generated": {"by": "oto factory scope", "at": "2026-10-27"}}
    run.update(more)
    os.makedirs(os.path.join(cwd, ".factory"), exist_ok=True)
    with open(os.path.join(cwd, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump(run, f)
    return run


def _read_run(cwd):
    with open(os.path.join(cwd, ".factory", "run.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- the guard ----

def test_the_guard_refuses_an_edit_outside_the_write_scope_and_inside_the_read_only_paths(tmp_path):
    cwd = str(tmp_path)
    _snapshot(cwd)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse"}
    code, out, err = _hook(GUARD, dict(base, tool_name="Edit", tool_input={"file_path": os.path.join(cwd, "src", "intake", "app.py")}), cwd)
    assert code == 0, (out, err)
    code, out, err = _hook(GUARD, dict(base, tool_name="Write", tool_input={"file_path": "tests/intake/test_app.py", "content": "x"}), cwd)
    assert code == 0, (out, err)
    code, out, err = _hook(GUARD, dict(base, tool_name="Edit", tool_input={"file_path": "src/scheduler/main.py"}), cwd)
    assert code == 2 and "outside the write scope" in err and "src/intake" in err and "Invoice intake" in err, err
    code, out, err = _hook(GUARD, dict(base, tool_name="Write", tool_input={"file_path": os.path.join(cwd, "contracts", "invoice-events.v1.json"), "content": "{}"}), cwd)
    assert code == 2 and "read-only" in err and "contracts" in err and "new version" in err, err
    code, out, err = _hook(GUARD, dict(base, tool_name="MultiEdit", tool_input={"file_path": "../elsewhere/x.py"}), cwd)
    assert code == 2 and "outside the write scope" in err
    code, out, err = _hook(GUARD, dict(base, tool_name="NotebookEdit", tool_input={"notebook_path": "src/intake/notes.ipynb"}), cwd)
    assert code == 0, err
    code, out, err = _hook(GUARD, dict(base, tool_name="Read", tool_input={"file_path": "contracts/invoice-events.v1.json"}), cwd)
    assert code == 0, "reading a contract is what a runner should do"
    code, out, err = _hook(GUARD, dict(base, tool_name="Grep", tool_input={"pattern": "x", "path": "contracts"}), cwd)
    assert code == 0


def test_the_guard_refuses_a_shell_command_that_writes_a_read_only_path(tmp_path):
    cwd = str(tmp_path)
    _snapshot(cwd)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Bash"}
    for command in ("cat contracts/invoice-events.v1.json", "ls contracts", "pytest tests/intake", "git diff -- contracts/"):
        code, out, err = _hook(GUARD, dict(base, tool_input={"command": command}), cwd)
        assert code == 0, (command, err)
    for command in ("echo '{}' > contracts/invoice-events.v1.json", "rm contracts/invoice-events.v1.json", "sed -i '' 's/a/b/' contracts/x.json",
                    "mv contracts/a.json contracts/b.json", "tee contracts/x.json < y", "touch contracts/new.json"):
        code, out, err = _hook(GUARD, dict(base, tool_input={"command": command}), cwd)
        assert code == 2 and "read-only" in err, (command, err)


def test_the_guard_does_nothing_without_a_run_and_fails_closed_on_a_broken_snapshot(tmp_path):
    cwd = str(tmp_path)
    payload = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "anything/at/all.py"}}
    code, out, err = _hook(GUARD, payload, cwd)
    assert code == 0 and not err.strip(), "no run in this directory: the plugin stays out of the way"
    os.makedirs(os.path.join(cwd, ".factory"))
    with open(os.path.join(cwd, ".factory", "run.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    code, out, err = _hook(GUARD, payload, cwd)
    assert code == 2 and "run.json" in err, "a run whose scope cannot be read blocks every edit: fail closed"
    with open(os.path.join(cwd, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump({"component": "x"}, f)
    code, out, err = _hook(GUARD, payload, cwd)
    assert code == 2 and "write_scope" in err
    code, out, err = _hook(GUARD, {"hook_event_name": "PreToolUse"}, cwd)
    assert code == 2, "no cwd and a broken snapshot in the working directory: still closed"


# ---- the loop ----

def test_the_stop_hook_keeps_the_loop_going_on_the_evaluator_s_gaps_and_stops_at_the_cap(tmp_path):
    cwd = str(tmp_path)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "Stop", "stop_hook_active": False}
    code, out, err = _hook(LOOP, base, cwd)
    assert code == 0 and not out.strip(), "no run: not a factory session, nothing to say"
    _snapshot(cwd, cap=2)
    code, out, err = _hook(LOOP, base, cwd)
    assert code == 0, err
    reply = json.loads(out)
    assert reply["decision"] == "block" and "iteration 1 of 2" in reply["reason"] and "no verdict" in reply["reason"] and "evaluator" in reply["reason"]
    assert _read_run(cwd)["iteration"] == 1
    with open(os.path.join(cwd, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "fail", "gaps": ["the IBAN is not validated", "no test for a duplicate invoice"]}, f)
    code, out, err = _hook(LOOP, dict(base, stop_hook_active=True), cwd)
    reply = json.loads(out)
    assert reply["decision"] == "block" and "iteration 2 of 2" in reply["reason"] and "IBAN" in reply["reason"] and "duplicate invoice" in reply["reason"]
    assert _read_run(cwd)["iteration"] == 2
    code, out, err = _hook(LOOP, dict(base, stop_hook_active=True), cwd)
    assert code == 0 and "block" not in out, "the cap: the loop cannot run forever"
    assert "cap" in (out + err) and "2" in (out + err) and "person" in (out + err)
    run = _read_run(cwd)
    assert run["iteration"] == 2 and run["escalated"] is True
    with open(os.path.join(cwd, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "pass", "gaps": []}, f)
    _snapshot(cwd, cap=5, iteration=1)
    code, out, err = _hook(LOOP, base, cwd)
    assert code == 0 and "block" not in out and "passed" in (out + err), "a pass ends the loop"
    assert _read_run(cwd)["iteration"] == 1, "a pass is not an iteration"


def test_the_stop_hook_cannot_be_skipped_by_a_broken_verdict(tmp_path):
    cwd = str(tmp_path)
    _snapshot(cwd, cap=3)
    with open(os.path.join(cwd, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        f.write("not json")
    code, out, err = _hook(LOOP, {"cwd": cwd, "hook_event_name": "Stop", "stop_hook_active": False}, cwd)
    reply = json.loads(out)
    assert reply["decision"] == "block" and "verdict.json" in reply["reason"], "a verdict that cannot be read is no verdict"
    with open(os.path.join(cwd, ".factory", "verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"verdict": "maybe"}, f)
    code, out, err = _hook(LOOP, {"cwd": cwd, "hook_event_name": "Stop", "stop_hook_active": False}, cwd)
    assert json.loads(out)["decision"] == "block"


# ---- the scope, from the graph ----

@pytest.fixture
def domain(tmp_path):
    root = str(tmp_path / "domain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="domain", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


def test_scope_writes_the_run_snapshot_from_the_code_map(domain, tmp_path):
    out_path = str(tmp_path / "repo" / ".factory" / "run.json")
    code, out = _cli("factory", "scope", "component.invoice-intake", "--cap", "4", "--allow", "tests/intake", "--out", out_path, "--project", domain)
    assert code == 0, out
    assert "src/intake" in out and "tests/intake" in out and "contracts" in out and "cap 4" in out, out
    with open(out_path, encoding="utf-8") as f:
        run = json.load(f)
    assert run["component"] == "component.invoice-intake" and run["label"] == "Invoice intake"
    assert run["write_scope"] == ["src/intake", "tests/intake"] and run["read_only"] == ["contracts"]
    assert run["cap"] == 4 and run["iteration"] == 0 and run["generated"]["by"] == "oto factory scope"
    assert run["spec_hash"] and len(run["spec_hash"]) == 64, "the spec the run builds against, by its hash"
    code, out = _cli("factory", "scope", "component.approval-policy", "--out", str(tmp_path / "x.json"), "--project", domain)
    assert code == 1 and "no module" in out and "oto arch map" in out and "--allow" in out, "no code map for it: nothing to scope, said with the way out"
    code, out = _cli("factory", "scope", "component.approval-policy", "--allow", "src/policy", "--read-only", "schemas", "--out", str(tmp_path / "y.json"), "--project", domain)
    assert code == 0, out
    with open(str(tmp_path / "y.json"), encoding="utf-8") as f:
        run = json.load(f)
    assert run["write_scope"] == ["src/policy"] and run["read_only"] == ["contracts", "schemas"] and run["cap"] == 5
    code, out = _cli("factory", "scope", "component.nope", "--out", str(tmp_path / "z.json"), "--project", domain)
    assert code == 1 and "component.nope" in out
    code, out = _cli("factory", "scope", "component.invoice-intake", "--cap", "0", "--out", str(tmp_path / "w.json"), "--project", domain)
    assert code == 1 and "cap" in out


# ---- the agents and the packaging ----

def _frontmatter(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("---\n"), path
    head, body = text[4:].split("\n---\n", 1)
    front = {}
    for line in head.splitlines():
        key, _sep, value = line.partition(":")
        front[key.strip()] = value.strip()
    return front, body


def test_the_agents_are_defined_and_the_evaluator_never_sees_the_runner_s_reasoning():
    runner, runner_body = _frontmatter(os.path.join(PLUGIN, "agents", "runner.md"))
    evaluator, evaluator_body = _frontmatter(os.path.join(PLUGIN, "agents", "evaluator.md"))
    aggregator, aggregator_body = _frontmatter(os.path.join(PLUGIN, "agents", "aggregator.md"))
    assert runner["name"] == "factory-runner" and evaluator["name"] == "factory-evaluator" and aggregator["name"] == "factory-aggregator"
    runner_tools = {t.strip() for t in runner["tools"].split(",")}
    evaluator_tools = {t.strip() for t in evaluator["tools"].split(",")}
    assert {"Read", "Edit", "Write", "Bash"} <= runner_tools
    assert not evaluator_tools & {"Edit", "Write", "MultiEdit", "NotebookEdit"}, "the evaluator judges; it never writes the code"
    assert "Bash" in evaluator_tools and "Read" in evaluator_tools, "it runs the tests and reads the code"
    assert "reasoning" in evaluator_body and "never" in evaluator_body and "spec" in evaluator_body and "verdict.json" in evaluator_body
    assert "write scope" in runner_body.lower() and "contracts" in runner_body and "verdict" in runner_body.lower()
    assert "verdict" in aggregator_body.lower() and "promot" in aggregator_body.lower()
    for body in (runner_body, evaluator_body, aggregator_body):
        assert ".factory/run.json" in body or "run.json" in body


def test_the_plugin_is_packaged_and_listed_in_the_marketplace():
    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        plugin = json.load(f)
    assert plugin["name"] == "oto-factory" and plugin["version"] and plugin["license"] == "Apache-2.0"
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
        plugins = {p["name"]: p for p in json.load(f)["plugins"]}
    assert plugins["oto-factory"]["source"] == "./factory" and plugins["oto-factory"]["version"] == plugin["version"]
    assert "oto" in plugins, "the engine's own plugin stays listed"
    with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    pre = [h for group in hooks["PreToolUse"] for h in group["hooks"]]
    stop = [h for group in hooks["Stop"] for h in group["hooks"]]
    assert any("${CLAUDE_PLUGIN_ROOT}/hooks/guard.py" in h["command"] for h in pre) and any("${CLAUDE_PLUGIN_ROOT}/hooks/loop.py" in h["command"] for h in stop)
    assert all(h["type"] == "command" for h in pre + stop)
    matcher = hooks["PreToolUse"][0].get("matcher", "")
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
        assert tool in matcher, "the guard sees every tool that writes"
    with open(os.path.join(PLUGIN, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "oto factory scope" in readme and "write scope" in readme.lower() and "iteration cap" in readme.lower() and "Epic E" in readme
    for script in (GUARD, LOOP):
        with open(script, encoding="utf-8") as f:
            text = f.read()
        assert "import json" in text and "oto" not in [line.split()[1] for line in text.splitlines() if line.startswith("import ") or line.startswith("from ")], \
            "the hooks are plain Python: no engine on the runner's machine"
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        assert "factory/" in f.read()
