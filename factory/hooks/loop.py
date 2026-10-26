#!/usr/bin/env python3
"""The factory's Stop hook (roadmap J2): the loop runs on the evaluator's gaps and stops at the
iteration cap, so it can be neither skipped nor run forever.

Reads the hook's JSON on stdin (cwd, stop_hook_active) and the run snapshot at
`<cwd>/.factory/run.json` ({"cap", "iteration", ...}); the evaluator's verdict is
`<cwd>/.factory/verdict.json` ({"verdict": "pass" | "fail", "gaps": [...], "tests": "pass" | "fail"}). No snapshot: not a
factory run, the session stops as usual. A pass ends the loop. Otherwise the hook counts the
iteration, appends what it decided to `events.jsonl` beside the snapshot (J4: `oto factory run
sync` reads it into the run graph) and answers {"decision": "block", "reason": ...} so the agent keeps going on the gaps
(or, with no readable verdict, runs the evaluator first), until the cap, where it lets the session
stop, marks the run escalated and says so: a person takes it from there. Plain Python, no engine.
"""
import datetime
import json
import os
import sys


def event(snapshot, run, kind, iteration, verdict=None, gaps=None, tests=None):
    """One line appended to events.jsonl beside the snapshot: what the loop decided, for
    `oto factory run sync` to read into the run graph (roadmap J4); `tests` is what the evaluator
    said the tests said, so the metrics can tell where the two disagreed (J6)."""
    line = {"event": kind, "run": run.get("run"), "component": run.get("component"), "iteration": iteration, "verdict": verdict or "pending",
            "gaps": list(gaps or []), "tests": tests if tests in ("pass", "fail") else "unknown",
            "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        with open(os.path.join(os.path.dirname(snapshot), "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    snapshot = os.environ.get("FACTORY_RUN") or os.path.join(cwd, ".factory", "run.json")
    if not os.path.isfile(snapshot):
        return 0
    try:
        with open(snapshot, encoding="utf-8") as f:
            run = json.load(f)
        if not isinstance(run, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        sys.stdout.write(json.dumps({"decision": "block", "reason": "factory: %s cannot be read (%s); fix the run snapshot before stopping" % (snapshot, exc)}) + "\n")
        return 0
    label = run.get("label") or run.get("component") or "the component"
    try:
        cap = max(int(run.get("cap") or 5), 1)
    except (TypeError, ValueError):
        cap = 5
    try:
        iteration = max(int(run.get("iteration") or 0), 0)
    except (TypeError, ValueError):
        iteration = 0
    verdict_path = os.path.join(os.path.dirname(snapshot), "verdict.json")
    verdict, gaps, tests, problem = None, [], None, None
    if os.path.isfile(verdict_path):
        try:
            with open(verdict_path, encoding="utf-8") as f:
                data = json.load(f)
            verdict = str((data or {}).get("verdict") or "").strip().lower()
            gaps = [str(g) for g in ((data or {}).get("gaps") or [])]
            tests = str((data or {}).get("tests") or "").strip().lower() or None
            if verdict not in ("pass", "fail"):
                problem = "verdict.json says %r; a verdict is pass or fail" % verdict
                verdict = None
        except (OSError, ValueError) as exc:
            problem = "verdict.json cannot be read (%s)" % exc
    if verdict == "pass":
        event(snapshot, run, "pass", iteration, "pass", gaps, tests)
        sys.stdout.write("factory: the evaluator passed %s after %d iteration(s); the run is done\n" % (label, iteration))
        return 0
    if iteration >= cap:
        run["escalated"] = True
        with open(snapshot, "w", encoding="utf-8") as f:
            json.dump(run, f, indent=2)
        event(snapshot, run, "escalated", iteration, verdict or "pending", gaps, tests)
        sys.stdout.write("factory: the iteration cap of %d is reached for %s without a pass; the run is escalated to a person and stays recorded in %s\n"
                         % (cap, label, snapshot))
        return 0
    run["iteration"] = iteration + 1
    with open(snapshot, "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2)
    event(snapshot, run, "iteration", iteration + 1, verdict or "pending", gaps, tests)
    if verdict == "fail":
        what = "the evaluator's gaps: %s. Act on each, run the tests, then run the evaluator again" % ("; ".join(gaps) if gaps else "none listed; run the evaluator again")
    elif problem:
        what = "%s; run the evaluator on the spec, the criteria and the diff, and write a verdict.json with pass or fail and the gaps" % problem
    else:
        what = "no verdict.json yet: run the evaluator on the spec, the criteria and the diff, and act on its gaps"
    reason = "factory iteration %d of %d for %s: %s" % (iteration + 1, cap, label, what)
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
