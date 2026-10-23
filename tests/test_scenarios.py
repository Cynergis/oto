"""End-to-end scenarios: a project built the way an analyst builds one, step by step through the CLI,
with what each step must produce.

Each folder under `tests/scenarios/` holds a `scenario.json` and what it needs (a `sources.py` that
writes the documents, proposals, vocabulary files, a gold set). A step does one of:

    run      a CLI command; `--project` is added. `exit` (default 0), `out` and `not_out` (text the
             output must or must not contain), and one structured expectation:
               findings  `curate check`'s findings by severity, [[subject, text], ...]; every severity
                         not listed must be empty, so `{}` means a clean check
               warnings  `capture`'s notes, exactly these
               rows      `query ask`'s answer rows, exactly these (each a subset of a row's fields)
               bench     floors per system on the strict answers table; `beats` names the systems
                         each must outscore
    snapshot the workbench snapshot after the step (`oto status --snapshot`): {path: expected}, where a
             path is dotted keys, a list item by its id or name (`stations.curate.state`), and expected is a
             value, or {"len": n}, {"min": x} or {"has": text} (in the value's JSON)
    file     a JSON file the project holds, checked like a snapshot: {"file": path, "json": {path: expected}}
    inbox    copy source documents into the inbox
    write    write a file into the project (`text`)
    put      copy a scenario file or folder into the project (`to`, default its root)
    replay   run another scenario's steps, through the step whose `id` is `through`

Paths in a step may use {scenario}, {sources} and {root}. Expectations are facts about the result, not
transcripts of it: a reworded message fails a test only where the scenario quotes it.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil

import pytest

HERE = os.path.join(os.path.dirname(__file__), "scenarios")
NAMES = sorted(n for n in os.listdir(HERE) if os.path.exists(os.path.join(HERE, n, "scenario.json")))
SEVERITIES = ("blocking", "contradiction", "gap")


def _load(name):
    with open(os.path.join(HERE, name, "scenario.json"), encoding="utf-8") as f:
        return json.load(f)


def _cli(args):
    from oto.cli import main
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(args)
        except SystemExit as exc:
            code = exc.code
    return code or 0, out.getvalue()


def _fill(value, ctx):
    return value.format(**ctx) if isinstance(value, str) else value


def findings(text):
    """{severity: [(subject, detail)]} from `curate check`'s report."""
    out, current = {s: [] for s in SEVERITIES}, None
    for line in text.splitlines():
        head = re.match(r"^(blocking|contradiction|gap) \(\d+\):$", line)
        if head:
            current = head.group(1)
        elif current and line.startswith("  ") and not line.startswith("  ..."):
            subject, _, detail = line.strip().partition(" ")
            out[current].append((subject, detail.strip()))
        else:
            current = None
    return out


def rows(text):
    """The answer rows of `query ask`: one dict per line after the status line."""
    out, started = [], False
    for line in text.splitlines():
        if line.startswith("status:"):
            started = True
        elif started and line.startswith("  ") and "=" in line:
            out.append(dict(re.findall(r"(\S+?)=(.*?)(?=\s{2,}\S+?=|$)", line.strip())))
    return out


def answers(text):
    """{system: {right, wrong, abstained, precision, coverage, score}} from the bench's strict table."""
    out, table = {}, text.split("ANSWERS", 1)[-1]
    for m in re.finditer(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)", table, re.M):
        out[m.group(1)] = dict(zip(("right", "wrong", "abstained"), map(int, m.group(2, 3, 4))),
                               **dict(zip(("precision", "coverage", "score"), map(float, m.group(5, 6, 7)))))
    return out


def _expect(step, code, text, where):
    said = "%s\n--- output ---\n%s" % (where, text)
    assert code == step.get("exit", 0), "exit %s, not %s: %s" % (code, step.get("exit", 0), said)
    for part in step.get("out", []):
        assert part in text, "%r missing: %s" % (part, said)
    for part in step.get("not_out", []):
        assert part not in text, "%r present: %s" % (part, said)
    if "findings" in step:
        found = findings(text)
        for severity in SEVERITIES:
            wanted = step["findings"].get(severity, [])
            for subject, part in wanted:
                assert any(s == subject and part in d for s, d in found[severity]), \
                    "no %s finding %s %r: %s" % (severity, subject, part, said)
            assert len(found[severity]) == len(wanted), "%s findings %s, expected %d: %s" % (
                severity, found[severity], len(wanted), said)
    if "warnings" in step:
        notes = [line.strip()[len("note: "):] for line in text.splitlines() if line.strip().startswith("note: ")]
        assert len(notes) == len(step["warnings"]), "warnings %s: %s" % (notes, said)
        for part in step["warnings"]:
            assert any(part in n for n in notes), "no warning %r: %s" % (part, said)
    if "rows" in step:
        got = rows(text)
        assert len(got) == len(step["rows"]), "rows %s: %s" % (got, said)
        for wanted in step["rows"]:
            assert any(all(r.get(k) == v for k, v in wanted.items()) for r in got), "no row %s: %s" % (wanted, said)
    if "bench" in step or "beats" in step:
        table = answers(text)
        for system, floors in step.get("bench", {}).items():
            for metric, floor in floors.items():
                assert table[system][metric] >= floor, "%s %s %s < %s: %s" % (system, metric, table[system][metric], floor, said)
        for system, others in step.get("beats", {}).items():
            for other in others:
                assert table[system]["score"] > table[other]["score"], "%s does not beat %s: %s" % (system, other, said)


def _at(value, path):
    for key in path.split("."):
        if isinstance(value, list):
            value = next(item for item in value if isinstance(item, dict) and key in (item.get("id"), item.get("name"))) \
                if not key.isdigit() else value[int(key)]
        else:
            value = value[key]
    return value


def _snapshot(step, ctx, where):
    code, text = _cli(["status", "--project", ctx["root"], "--snapshot"])
    assert code == 0, "%s: no snapshot\n%s" % (where, text)
    _match(json.loads(text), step["snapshot"], where + ": snapshot")


def _json_file(step, ctx, where):
    path = os.path.join(ctx["root"], step["file"])
    assert os.path.exists(path), "%s: no %s" % (where, step["file"])
    with open(path, encoding="utf-8") as f:
        _match(json.load(f), step["json"], "%s: %s" % (where, step["file"]))


def _match(snap, expected, where):
    for path, wanted in expected.items():
        try:
            got = _at(snap, path)
        except (KeyError, IndexError, StopIteration):
            raise AssertionError("%s has no %s" % (where, path))
        said = "%s %s is %s" % (where, path, json.dumps(got, ensure_ascii=False)[:600])
        if isinstance(wanted, dict) and set(wanted) <= {"len", "min", "has"}:
            if "len" in wanted:
                assert len(got) == wanted["len"], said
            if "min" in wanted:
                assert got >= wanted["min"], said
            if "has" in wanted:
                assert wanted["has"] in json.dumps(got, ensure_ascii=False), said
        else:
            assert got == wanted, "%s, expected %s" % (said, json.dumps(wanted, ensure_ascii=False))


def _play(name, ctx, through=None, done=None):
    scenario = _load(name)
    ctx = dict(ctx, scenario=os.path.join(HERE, name))
    for number, step in enumerate(scenario["steps"], 1):
        where = "%s step %d (%s)" % (name, number, step.get("say") or " ".join(step.get("run", [])) or step)
        if "replay" in step:
            _play(step["replay"], ctx, through=step["through"])
        elif "inbox" in step:
            for doc in step["inbox"]:
                shutil.copy(os.path.join(ctx["sources"], doc), os.path.join(ctx["root"], "inbox", doc))
        elif "write" in step:
            path = os.path.join(ctx["root"], step["write"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(step["text"])
        elif "put" in step:
            src, dst = os.path.join(ctx["scenario"], step["put"]), os.path.join(ctx["root"], step.get("to", ""))
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dst) if step.get("to") else dst, exist_ok=True)
                shutil.copy(src, dst)
        if "run" in step:
            args = [_fill(a, ctx) for a in step["run"]]
            code, text = _cli(args[:1] + ["--project", ctx["root"]] + args[1:])
            _expect(step, code, text, where)
        if "snapshot" in step:
            _snapshot(step, ctx, where)
        if "file" in step:
            _json_file(step, ctx, where)
        if through and step.get("id") == through:
            return
    assert not through, "%s has no step with id %r" % (name, through)


@pytest.mark.parametrize("name", NAMES)
def test_scenario(name, tmp_path, monkeypatch):
    scenario = _load(name)
    for module in scenario.get("requires", []):
        pytest.importorskip(module)
    sources = str(tmp_path / "sources")
    for folder in [name] + sorted({s["replay"] for s in scenario["steps"] if "replay" in s}):
        builder = _load(folder).get("sources")
        if builder:
            spec = importlib.util.spec_from_file_location("scenario_sources", os.path.join(HERE, folder, builder))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.make(sources)
    monkeypatch.chdir(tmp_path)
    _play(name, {"root": str(tmp_path / "project"), "sources": sources})


def test_every_scenario_says_what_it_is_and_every_replay_point_exists():
    for name in NAMES:
        scenario = _load(name)
        assert scenario.get("name") and scenario.get("about"), name
        for step in scenario["steps"]:
            if "replay" in step:
                assert any(s.get("id") == step["through"] for s in _load(step["replay"])["steps"]), (name, step)
