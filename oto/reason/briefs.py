# -*- coding: utf-8 -*-
"""Briefs: what an agent must know before a task, as the questions it must be able to answer.

A brief is a task type: its parameters, the competency questions it requires and the ones it may
also read. Run against the graph with the parameters bound, it is READY when every required
question is answered and BLOCKED otherwise, naming the questions and their gaps, so the agent
that is about to write a step's script, or tests for it, is stopped by name rather than guessing.

    {"implement-step": {"description": "An agent is about to write the script for one flow step.",
                        "params": {"STEP": "Step"},
                        "required": ["FL1", "FL2", "FL4"], "optional": ["FL7"]}}

`briefs.json` lives beside `questions.json`, is carried by an ontology (manifest `carries`:
"briefs"), composes by task id like the questions, and rides in the store so `kg_brief` runs it.
"""
import json
import os

NAME = "briefs.json"
#: A required question with one of these statuses blocks the brief.
BLOCKING_STATUSES = ("unanswered", "violated")


def path_for(project):
    return os.path.join(project.data, NAME)


def load(project):
    """{task: brief}, or {} when the project declares none."""
    path = path_for(project)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return dict((data.get("briefs") if isinstance(data, dict) and "briefs" in data else data) or {})


def save(project, briefs):
    with open(path_for(project), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_about": "What an agent must know before a task: the questions it must be able to answer "
                             "(required) and the ones it may also read (optional), with the parameters the task "
                             "is about. `oto query brief <task> NAME=<entity>` is READY or BLOCKED by name.",
                   "briefs": briefs}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def problems(briefs, questions):
    """What is wrong with the briefs against the questions they name. Empty means usable."""
    out = []
    if not isinstance(briefs, dict):
        return ["briefs.json must hold {task: {description, params, required, optional}}"]
    for task, brief in briefs.items():
        label = "brief %r" % task
        if not isinstance(brief, dict):
            out.append("%s: must be an object" % label)
            continue
        if not (brief.get("description") or "").strip():
            out.append("%s: needs a description: what the agent is about to do" % label)
        params = brief.get("params") or {}
        if not isinstance(params, dict):
            out.append("%s: params must map NAME -> class" % label)
            params = {}
        required, optional = brief.get("required") or [], brief.get("optional") or []
        if not required:
            out.append("%s: requires no question; a brief that cannot block is not a gate" % label)
        for which, ids in (("required", required), ("optional", optional)):
            for qid in ids:
                if qid not in (questions or {}):
                    out.append("%s: %s question %r is not declared in questions.json" % (label, which, qid))
                    continue
                for name in (questions[qid].get("params") or {}):
                    if name not in params:
                        out.append("%s: question %s needs parameter %s, which the brief does not declare" % (label, qid, name))
        if set(required) & set(optional):
            out.append("%s: a question is both required and optional: %s" % (label, ", ".join(sorted(set(required) & set(optional)))))
    return out


def run(task, brief, params, questions, nodes, edges, covers=None, derived_attributes=None, declared=None):
    """One brief with its parameters bound (NAME -> node id): {task, description, params, status,
    questions: [the question results, each with `required`], blocking: [{id, status, gaps}]}."""
    from . import questions as _questions
    results = []
    for which, ids in (("required", brief.get("required") or []), ("optional", brief.get("optional") or [])):
        for qid in ids:
            question = questions.get(qid)
            if question is None:
                continue
            bound = {k: v for k, v in (params or {}).items() if k in (question.get("params") or {})}
            result = _questions.run(qid, question, bound, nodes, edges, covers, derived_attributes, declared)
            result["required"] = which == "required"
            results.append(result)
    blocking = [{"id": r["id"], "status": r["status"], "gaps": r["gaps"] or ["the required question returned no facts"]}
                for r in results if r["required"] and r["status"] in BLOCKING_STATUSES]
    return {"task": task, "description": brief.get("description") or "", "params": dict(params or {}),
            "status": "BLOCKED" if blocking else "READY", "questions": results, "blocking": blocking}


def text(result, labels=None):
    """A brief as text: the verdict, then every question with its facts, then what blocks."""
    from . import questions as _questions
    labels = labels or {}
    shown = ", ".join("%s=%s" % (k, labels.get(v, v)) for k, v in result["params"].items())
    lines = ["%s  %s->  %s" % (result["task"], ("%s  " % shown) if shown else "", result["status"])]
    if result.get("description"):
        lines.append("  %s" % result["description"])
    for r in result["questions"]:
        mark = {"answered": "+", "clean": "+", "empty": "o", "unanswered": "x", "violated": "x"}.get(r["status"], "?")
        lines.append("  %s %s %s  %s  [%d fact(s)]" % (mark, r["id"], "REQ" if r["required"] else "opt", r["question"], len(r["rows"])))
        for gap in r["gaps"]:
            lines.append("        gap: %s" % gap)
    if result["status"] == "BLOCKED":
        lines.append("  blocked on: " + ", ".join(b["id"] for b in result["blocking"]))
    return "\n".join(lines)


def table(task, brief, questions, nodes, edges, covers=None, derived_attributes=None, declared=None):
    """A brief run for every entity its first parameter can bind to: [(node id, label, result)].
    What `readiness` is: which steps may be implemented, which are blocked and on what."""
    from .match import Graph, BELIEVED
    from .questions import _kinds
    params = brief.get("params") or {}
    if not params:
        return [(None, "", run(task, brief, {}, questions, nodes, edges, covers, derived_attributes, declared))]
    first = next(iter(params))
    graph = Graph(nodes, edges, derived_attributes, statuses=BELIEVED, covers=covers, declared=declared)
    kinds = set()
    for one in _kinds(params[first]):
        kinds |= set(graph.covers.get(one, {one}))
    out = []
    for nid in sorted(graph.nodes):
        if graph.nodes[nid].get("type") in kinds:
            out.append((nid, graph.nodes[nid].get("label") or nid,
                        run(task, brief, {first: nid}, questions, nodes, edges, covers, derived_attributes, declared)))
    return out


def table_text(rows):
    lines = []
    for nid, label, result in rows:
        verdict = result["status"] if result["status"] == "READY" else "BLOCKED " + ",".join(b["id"] for b in result["blocking"])
        lines.append("%-40s %s" % (nid or label or "(graph)", verdict))
    ready = sum(1 for _n, _l, r in rows if r["status"] == "READY")
    lines.append("%d READY, %d BLOCKED" % (ready, len(rows) - ready))
    return "\n".join(lines)
