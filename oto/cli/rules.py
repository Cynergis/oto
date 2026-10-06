# -*- coding: utf-8 -*-
"""`oto rules`: validate the rule set, dry-run it, diff it against the accepted one, accept it,
and explain one: its recorded reason, its pattern, and what it did on the last build."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_rules(args):
    from ..model import vocabulary as _vocab
    from ..reason import engine as _engine, rules as _rules

    project = _resolve(args)
    declared = _rules.load(project)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)

    if args.rules_command == "explain":
        return _explain(project, declared, args.rule_id, args.show)

    if args.rules_command == "accept":
        problems = _rules.problems(declared, vocabulary)
        if problems:
            print("oto: refusing to accept a rule set with problems; run `oto rules check`", file=sys.stderr)
            return 1
        current = _vocab.Vocabulary.from_config(vocabulary)
        _vocab.write_lock(project, current, rules=declared)
        print("accepted %d rule(s) with vocabulary version %d" % (len(declared), current.version))
        return 0

    if args.rules_command == "diff":
        locked = _rules.read_lock(project)
        if locked is None:
            print("no accepted vocabulary on record; `oto rules accept` records this rule set as the baseline")
            return 0
        added, removed, changed = _rules.diff(locked, declared)
        if not (added or removed or changed):
            print("no change to the rules since they were accepted")
            return 0
        for rid in removed:
            print("  [breaking ] removed   %s: facts it derived will go on the next build" % rid)
        for rid in changed:
            print("  [breaking ] changed   %s: what it derives or flags is different" % rid)
        for rid in added:
            print("  [additive ] added     %s" % rid)
        print("\nRun `oto rules accept` once these are deliberate.")
        return 1 if (removed or changed) and args.strict else 0

    # check: validate, then dry-run over the live graph
    problems = _rules.problems(declared, vocabulary)
    if not declared:
        print("no rules declared (rules.json absent or empty)")
        return 0
    if problems:
        print("%d problem(s) in rules.json:" % len(problems))
        for problem in problems[:args.show * 2]:
            print("  %s" % problem)
        return 1
    try:
        outcome = _engine.run(declared, graph.get("nodes") or [], graph.get("edges") or [],
                              covers=_vocab.covers(vocabulary.get("classes") or {}))
    except _engine.DoesNotConverge as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    print("%d rule(s), %d round(s) to the fixpoint:" % (len(declared), outcome["rounds"]))
    for rule in declared:
        counts = outcome["per_rule"][rule["id"]]
        confirmed = "confirmed by %s" % rule["validated_by"] if (rule.get("validated_by") or "").strip() else "not yet confirmed"
        if rule["kind"] == "derive":
            print("  %-32s derive   %4d fact(s)   %s" % (rule["id"], counts["derived"], confirmed))
        else:
            print("  %-32s policy   %4d finding(s) [%s]   %s" % (rule["id"], counts["flagged"], rule.get("severity", "warn"), confirmed))
    for e in outcome["edges"][:args.show]:
        print("    derived  %s -%s-> %s   by %s" % (e["from"], e["rel"], e["to"], e["derived_by"]))
    for a in outcome["attributes"][:args.show]:
        print("    derived  %s.%s = %r   by %s" % (a["node"], a["name"], a["value"], a["derived_by"]))
    for f in outcome["findings"][:args.show]:
        print("    [%-8s] %s: %s: %s" % (f["severity"], f["rule"], f.get("node") or "(graph)", f["message"]))
    unconfirmed = sum(1 for r in declared if not (r.get("validated_by") or "").strip())
    if unconfirmed:
        print("\n%d rule(s) have no `validated_by`. A rule nobody confirmed derives facts nobody asked for; "
              "leave it empty rather than guessing." % unconfirmed)
    return 0


def _pattern(clause):
    """A rule clause as one readable phrase, in the rule model's own shapes (reason/rules.py)."""
    if "edge" in clause:
        a, rel, b = clause["edge"]
        return "%s -%s-> %s" % (a, rel, b)
    if "not_edge" in clause:
        a, rel, b = clause["not_edge"]
        return "no %s -%s-> %s" % (a, rel, b)
    if "node" in clause:
        return "%s is a %s" % (clause["node"], clause.get("type") or "node") + \
            ((" with %s" % json.dumps(clause["attrs"], ensure_ascii=False)) if clause.get("attrs") else "")
    if "attr" in clause:
        return "attr %s" % json.dumps(clause["attr"], ensure_ascii=False)
    return json.dumps(clause, ensure_ascii=False)


def _explain(project, declared, rule_id, show):
    """One rule, or every rule in one line each, with the reason its author wrote."""
    if not rule_id:
        if not declared:
            print("no rules declared (rules.json absent or empty)")
            return 0
        print("%d rule(s); `oto rules explain <id>` for one:" % len(declared))
        for rule in declared:
            print("  %-32s %-6s %s" % (rule["id"], rule["kind"], (rule.get("why") or "(no reason recorded)").strip()))
        return 0
    rule = next((r for r in declared if r["id"] == rule_id), None)
    if rule is None:
        print("oto: no rule %r; declared: %s" % (rule_id, ", ".join(r["id"] for r in declared) or "none"), file=sys.stderr)
        return 1
    print("%s  (%s%s)" % (rule["id"], rule["kind"], (", severity %s" % rule["severity"]) if rule.get("severity") else ""))
    print("  why:        %s" % ((rule.get("why") or "").strip() or "(no reason recorded: an unexplained rule derives facts nobody asked for)"))
    print("  confirmed:  %s" % ((rule.get("validated_by") or "").strip() or "by nobody yet (validated_by is empty)"))
    print("  when:       %s" % "  and  ".join(_pattern(c) for c in rule.get("when") or []))
    then = rule.get("then") or {}
    if rule["kind"] == "derive":
        print("  then:       %s" % ("derive " + _pattern(then) if then else "?"))
    else:
        print("  then:       flag \"%s\"" % (then.get("flag") or json.dumps(then, ensure_ascii=False)))
    derived = os.path.join(project.layout.graph, "derived.json")
    if not os.path.exists(derived):
        print("  last build: none yet (oto build); `oto rules check` dry-runs the rules over the graph")
        return 0
    with open(derived, encoding="utf-8") as f:
        result = json.load(f)
    edges = [e for e in result.get("derived_edges") or [] if e.get("derived_by") == rule_id]
    attrs = [a for a in result.get("derived_attributes") or [] if a.get("derived_by") == rule_id]
    findings = [x for x in result.get("findings") or [] if x.get("rule") == rule_id]
    print("  last build: %d edge(s), %d attribute(s) derived, %d finding(s)" % (len(edges), len(attrs), len(findings)))
    for e in edges[:show]:
        print("    %s -%s-> %s   because %s" % (e["from"], e["rel"], e["to"], ", ".join(e.get("premises") or [])))
    for a in attrs[:show]:
        print("    %s.%s = %r   because %s" % (a["node"], a["name"], a["value"], ", ".join(a.get("premises") or [])))
    for x in findings[:show]:
        print("    [%s] %s: %s" % (x["severity"], x.get("node") or "(graph)", x["message"]))
    if len(edges) + len(attrs) + len(findings) > show:
        print("    ... --show N for more")
    return 0


def register(sub):
    rules = sub.add_parser("rules", help="validate, dry-run, diff and accept the rules over the graph")
    rules.add_argument("rules_command", nargs="?", default="check", choices=["check", "diff", "accept", "explain"],
                       help="check validates and dry-runs; diff compares with the accepted set; accept records it; "
                            "explain <id> prints a rule's reason, its pattern and what it did on the last build")
    rules.add_argument("rule_id", nargs="?", default=None, help="for explain: the rule to explain (none: one line per rule)")
    project_arguments(rules)
    rules.add_argument("--show", type=int, default=10, help="how many items to list per section")
    rules.add_argument("--strict", action="store_true", help="for diff: exit non-zero on a breaking change")
    rules.set_defaults(func=cmd_rules)
