#!/usr/bin/env python3
"""The factory's PreToolUse guard (roadmap J2): an edit outside the run's write scope, or inside its
read-only paths, is refused before it happens.

Reads the hook's JSON on stdin (tool_name, tool_input, cwd) and the run snapshot at
`<cwd>/.factory/run.json` ({"component", "label", "write_scope": [paths or globs], "read_only":
[paths], ...}, written by `oto factory scope`; Epic E replaces the file with a signed policy
snapshot). No snapshot: not a factory run, the guard allows everything. A snapshot that cannot be
read blocks every write: the scope is unknown, so nothing is in it. Exit 2 refuses the tool and the
reason on stderr reaches the agent; exit 0 allows it. Plain Python, no engine needed on the runner's
machine.

With a policy snapshot beside it (`.factory/policy.json`, `oto policy snapshot --agent --principal`,
roadmap E3), the policy is the write scope: what the snapshot permits may be written, what it denies
may not, whatever run.json says; run.json still says what is read-only, the cap and the iteration.
The reader is `policy_snapshot.py` beside this file, the same file the engine plugin carries.
"""
import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_snapshot  # noqa: E402

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_MARKERS = re.compile(r"(^|[\s;|&(])(rm|mv|cp|tee|touch|truncate|chmod|chown|sed\s+-i|perl\s+-i|dd|install)\b|>>?|git\s+(checkout|restore|rm|mv)\b")


def refuse(reason):
    sys.stderr.write("factory guard: %s\n" % reason)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    snapshot = os.environ.get("FACTORY_RUN") or os.path.join(cwd, ".factory", "run.json")
    policed = os.path.isfile(policy_snapshot.where(cwd))
    if not os.path.isfile(snapshot) and not policed:
        return 0
    run = {}
    if os.path.isfile(snapshot):
        try:
            with open(snapshot, encoding="utf-8") as f:
                run = json.load(f)
        except (OSError, ValueError) as exc:
            refuse("%s cannot be read (%s): the run's scope is unknown, so no write is in it. Fix the snapshot or end the run" % (snapshot, exc))
        if not isinstance(run, dict) or (not policed and not isinstance(run.get("write_scope"), list)):
            refuse("%s is not a run snapshot: it names no write_scope. Write it with `oto factory scope <component>`" % snapshot)
    scope = [str(s).strip().strip("/") for s in run.get("write_scope") or [] if str(s).strip()]
    read_only = [str(s).strip().strip("/") for s in run.get("read_only") or [] if str(s).strip()]
    label = run.get("label") or run.get("component") or "the run"
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    def relative(path):
        path = str(path).replace("\\", "/")
        if os.path.isabs(path):
            try:
                path = os.path.relpath(path, cwd)
            except ValueError:
                return path
        path = os.path.normpath(path).replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        return path

    def within(path, patterns):
        for p in patterns:
            if path == p or path.startswith(p + "/") or fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p + "/*"):
                return True
        return False

    if tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not path:
            return 0
        rel = relative(path)
        if within(rel, read_only):
            refuse("%s is read-only in this run: the contracts are frozen; a change to one is a new version through the graph (oto decide, a new Contract), never an edit here" % rel)
        if policed:
            policy_snapshot.guard(payload, refuse)             # the policy is the write scope
            return 0
        if rel.startswith("../") or not within(rel, scope):
            refuse("%s is outside the write scope of %s: %s. The runner edits only what the spec's code map names; ask for the scope to be widened (oto factory scope --allow)"
                   % (rel, label, ", ".join(scope) or "nothing"))
        return 0
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if WRITE_MARKERS.search(command):
            for p in read_only:
                if re.search(r"(^|[\s'\"=/])%s(/|\b)" % re.escape(p), command):
                    refuse("the command touches %s, read-only in this run, with a verb that writes; the contracts are frozen" % p)
        if policed:
            policy_snapshot.guard(payload, refuse)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
