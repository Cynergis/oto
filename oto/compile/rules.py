# -*- coding: utf-8 -*-
"""Stage 2 of 5. Run the declared rules over the compiled graph.

Into `layout.graph`:
  derived.json   derived edges and attributes, each with the rule and the premises it rests on;
                 policy findings; per-rule counts

Derived facts never enter graph.json. They are recomputed on every build from the current facts,
so superseding a premise retires every derivation that rested on it, and the store loads them
marked. A project with no rules.json skips this stage with a note. A malformed rule set fails the
build; pre-flight reports the same problems first.
"""
import json
import os

from ..project import ProjectError
from ..reason import engine as _engine, rules as _rules


def run(project):
    layout = project.layout
    out = os.path.join(layout.graph, "derived.json")
    rules = _rules.load(project)
    if not rules:
        print("rules: none declared (rules.json absent or empty); nothing derived")
        if os.path.exists(out):
            os.remove(out)
        return

    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    problems = _rules.problems(rules, vocabulary)
    if problems:
        raise ProjectError("rules.json is not usable:\n  - " + "\n  - ".join(problems))

    with open(os.path.join(layout.graph, "knowledge-graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    try:
        from ..model.vocabulary import covers as _covers
        result = _engine.run(rules, graph["nodes"], graph["edges"], covers=_covers(vocabulary.get("classes") or {}))
    except _engine.DoesNotConverge as exc:
        raise ProjectError(str(exc))

    payload = {"rules": len(rules),
               "derived_edges": result["edges"], "derived_attributes": result["attributes"],
               "findings": result["findings"], "per_rule": result["per_rule"], "rounds": result["rounds"]}
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    blocking = sum(1 for x in result["findings"] if x["severity"] == "blocking")
    print("rules: %d rule(s) in %d round(s): %d edge(s) and %d attribute(s) derived, %d policy finding(s)%s"
          % (len(rules), result["rounds"], len(result["edges"]), len(result["attributes"]),
             len(result["findings"]), (" (%d blocking)" % blocking) if blocking else ""))
