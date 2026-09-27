# -*- coding: utf-8 -*-
"""`oto ontology`: the project's own vocabulary, and the catalog of ontologies it can start from.

A verb with no name acts on the project's ontology: check, accept, rationale, widen, import.
A verb with a name acts on the catalog (`catalog.py`): list, show, export, add, update, diff,
publish.
"""
import os
import sys

from . import catalog as _catalog
from ._common import project_arguments, resolve as _resolve


def cmd_ontology(args):
    import json as _json

    if args.ontology_command in _catalog.VERBS:
        return _catalog.run(args)

    from ..model import vocabulary as vocab

    project = _resolve(args)
    unacknowledged = 0
    with open(project.ontology_config_path, encoding="utf-8") as f:
        current = vocab.Vocabulary.from_config(_json.load(f))
    with open(project.graph_path, encoding="utf-8") as f:
        graph = _json.load(f)
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []

    if args.ontology_command == "import":
        from ..model import importer as _importer, ontologies as _ontologies

        if bool(args.file) == bool(args.from_name):
            print("oto: import needs exactly one of --file <vocabulary> or --ontology <name>[,<name>]",
                  file=sys.stderr)
            return 1
        rationale = None
        try:
            if args.from_name:
                names = [t.strip() for t in args.from_name.split(",") if t.strip()]
                for one in names:
                    if _ontologies.dir_for(one) is None:
                        raise ValueError("unknown ontology %r. Available: %s"
                                         % (one, ", ".join(_ontologies.available()) or "none"))
                if len(names) == 1:
                    config, _sample, _readme = _ontologies.load(names[0])
                    classes, properties = config["classes"], config["properties"]
                    rationale = _ontologies.rationale_for(names[0])
                    notes = []
                else:
                    config, _sample, _readme, rationale, report = _ontologies.merge(names)
                    classes, properties = config["classes"], config["properties"]
                    notes = ["class %s: described differently in %s and %s; kept %s" % (k, a, b, a)
                             for k, a, b in report["class_clashes"]]
                    notes += ["relation %s: domain or range differ in %s and %s; kept %s" % (r, a, b, a)
                              for r, a, b in report["relation_clashes"]]
                    notes.append("merged %d ontologies; prune before accepting" % len(names))
                attributes = config.get("attributes") or {}
            else:
                classes, properties, notes = _importer.read(args.file)
                attributes = _importer.read.attributes
            problems = _importer.check(classes, properties, attributes)
            if problems:
                print("the vocabulary is not usable as read:")
                for problem in problems[:args.show * 2]:
                    print("  %s" % problem)
                return 1
            path = _importer.apply(project, classes, properties, rationale=rationale, replace=args.replace,
                                   attributes=attributes)
        except (OSError, ValueError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("wrote %d class(es), %d relation(s) and %d attribute declaration(s) to %s"
              % (len(classes), len(properties), sum(len(v) for v in attributes.values()), os.path.basename(path)))
        for note in notes:
            print("  note: %s" % note)
        if rationale:
            print("  rationale carried over; validated_by is not a confirmation for this domain")
        else:
            print("  no rationale came with it: every class now lacks a recorded reason. Run the "
                  "ontology-interview skill, then `oto ontology rationale --strict`.")
        print("  then: oto ontology check, and oto ontology accept")
        return 0

    if args.ontology_command == "rationale":
        from ..model import rationale as _rationale

        record = _rationale.load(project)
        with open(project.ontology_config_path, encoding="utf-8") as f:
            config = _json.load(f)
        coverage = _rationale.report(config, record)
        print("recorded reasoning: %d of %d class(es), %d relation(s)"
              % (coverage["classes_with_rationale"], coverage["classes"],
                 coverage["properties_with_rationale"]))
        print("confirmed by a named person: %d class(es), %d relation(s)"
              % (len(coverage["classes_validated"]), len(coverage["properties_validated"])))
        if coverage["classes_missing"]:
            print("\nno recorded reason for %d class(es):" % len(coverage["classes_missing"]))
            for name in coverage["classes_missing"]:
                print("  %s" % name)
            print("\nA reviewer looking at a bare class list cannot tell a deliberate choice from an")
            print("accident, so the review that matters never happens. Record `question` and `why`.")
        if coverage["problems"]:
            print("\n%d problem(s):" % len(coverage["problems"]))
            for problem in coverage["problems"][:args.show]:
                print("  %s" % problem)
        unvalidated = coverage["classes"] - len(coverage["classes_validated"])
        if unvalidated:
            print("\n%d class(es) have no `validated_by`. Until a person who knows the domain fills"
                  % unvalidated)
            print("that in, the model is a draft. Leave it empty rather than guessing.")
        if args.strict and (coverage["problems"] or coverage["classes_missing"]):
            return 1
        return 0

    if args.ontology_command == "widen":
        from ..model import widen as _widen

        findings = _widen.analyse(
            _json.load(open(project.ontology_config_path, encoding="utf-8")), nodes, edges,
            frequent=args.frequent)
        if not findings:
            print("every edge already matches its declared domain and range")
            return 0

        widen_total = sum(sum(f["widen_domain"].values()) + sum(f["widen_range"].values())
                          for f in findings)
        inspect_total = sum(sum(f["inspect_domain"].values()) + sum(f["inspect_range"].values())
                            for f in findings)
        print("%d relation(s) are used in ways their declaration does not allow." % len(findings))
        print("  %d edge(s) in patterns seen %d+ times: the declaration never caught up." %
              (widen_total, args.frequent))
        print("  %d edge(s) in rarer patterns: more likely a mistake in the data." % inspect_total)
        print()
        for finding in findings[:args.show]:
            print("  %s" % finding["relation"])
            if finding["widen_domain"]:
                print("    domain %-34s add %s" % (
                    finding["declared_domain"],
                    ", ".join("%s (%d)" % (k, v) for k, v in finding["widen_domain"].items())))
            if finding["widen_range"]:
                print("    range  %-34s add %s" % (
                    finding["declared_range"],
                    ", ".join("%s (%d)" % (k, v) for k, v in finding["widen_range"].items())))
            for label, key in (("domain", "inspect_domain"), ("range", "inspect_range")):
                if finding[key]:
                    print("    %s INSPECT %s" % (label, ", ".join(
                        "%s (%d)" % (k, v) for k, v in finding[key].items())))
        if len(findings) > args.show:
            print("  ... and %d more relation(s)" % (len(findings) - args.show))

        config = _json.load(open(project.ontology_config_path, encoding="utf-8"))
        proposed, changed = _widen.propose(config, findings)
        path = _widen.write_proposal(project, proposed)
        print()
        print("Wrote a PROPOSAL, not a change: %s" % os.path.basename(path))
        print("  %d relation(s) widened, version raised to %d."
              % (len(changed), proposed["ontology_version"]))
        print("  Review it, then replace ontology.config.json with it and run `oto ontology accept`.")
        print("  The rarer patterns above are deliberately NOT widened: widening a mistake hides it")
        print("  permanently. Look at those edges and fix the data instead.")
        return 0

    if args.ontology_command == "accept":
        from ..reason import rules as _rules
        path = vocab.write_lock(project, current, rules=_rules.load(project))
        print("accepted vocabulary version %d (%d classes, %d relations, %d rules)"
              % (current.version, len(current.classes), len(current.properties), len(_rules.load(project))))
        print("wrote %s" % os.path.relpath(path, os.path.dirname(project.src)))
        return 0

    print("vocabulary: version %d, %d classes, %d relations"
          % (current.version, len(current.classes), len(current.properties)))

    locked = vocab.read_lock(project)
    breaking = 0
    if locked is None:
        print("\nno accepted vocabulary on record. Run `oto ontology accept` to record this one as "
              "the baseline, then future changes can be diffed against it.")
    else:
        changes = vocab.impact(vocab.diff(locked, current), nodes, edges)
        if not changes:
            print("\nno change since version %d was accepted" % locked.version)
        else:
            print("\n%d change(s) since version %d was accepted:" % (len(changes), locked.version))
            for change in changes:
                touches = (" — touches %d" % change.affected) if change.affected else ""
                print("  [%-9s] %-28s %-24s %s%s"
                      % (change.severity, change.kind, change.subject, change.detail, touches))
            breaking = sum(1 for c in changes if c.severity == vocab.Change.BREAKING)
            if breaking and current.version <= locked.version:
                unacknowledged = breaking
                print("\n%d breaking change(s) with no version bump. Raise `ontology_version` in "
                      "ontology.config.json, then run `oto ontology accept`." % breaking)
            elif breaking:
                unacknowledged = 0
                print("\n%d breaking change(s), acknowledged by the bump to version %d. Run "
                      "`oto ontology accept` to record it." % (breaking, current.version))

    report = vocab.conformance(current, nodes, edges)
    print("\ndomain and range conformance over %d declared edge(s):" % report["checked"])
    print("  domain violations: %d" % report["domain_violations"])
    print("  range violations : %d" % report["range_violations"])
    if report["domain_violations"] or report["range_violations"]:
        print("\n  These edges are declared but their endpoints do not match the declared domain or")
        print("  range. The integrity gate never checked this. It matters most for the RDF export,")
        print("  where domain and range are inference rules: a reasoner would infer the wrong type.")
        print("  Fix by widening the declaration to match how the relation is really used, or by")
        print("  correcting the edges.")
        for label, key in (("domain", "domain_patterns"), ("range", "range_patterns")):
            top = report[key][:args.show]
            if top:
                print("\n  worst %s mismatches:" % label)
                for (relation, actual, expected), count in top:
                    print("    %5d  %-22s endpoint is %-16s declared %s"
                          % (count, relation, actual, expected))

    attrs = vocab.attribute_conformance(current, nodes)
    declared = sum(len(v) for v in current.attributes.values())
    print("\nattributes: %d declared across %d class(es); %d value(s) checked, %d mistyped, %d undeclared key(s)"
          % (declared, len(current.attributes), attrs["checked"], len(attrs["mistyped"]), len(attrs["undeclared"])))
    for nid, key, why, value in attrs["mistyped"][:args.show]:
        print("  MISTYPED  %-28s %s = %r: %s" % (nid, key, value, why))
    for (kind, key), count in attrs["undeclared"][:args.show]:
        print("  undeclared %-27s %s.%s on %d node(s): declare it, or set strict_attributes to refuse it"
              % ("", kind, key, count))

    from ..reason import engine as _engine, rules as _rules
    declared_rules = _rules.load(project)
    if declared_rules:
        rule_problems = _rules.problems(declared_rules, _json.load(open(project.ontology_config_path, encoding="utf-8")))
        if rule_problems:
            print("\nrules.json is not usable:")
            for problem in rule_problems[:args.show]:
                print("  %s" % problem)
            return 1
        outcome = _engine.run(declared_rules, nodes, edges)
        blocking = [f for f in outcome["findings"] if f["severity"] == "blocking"]
        print("\nrules: %d declared; %d edge(s) and %d attribute(s) would be derived; %d policy finding(s)%s"
              % (len(declared_rules), len(outcome["edges"]), len(outcome["attributes"]), len(outcome["findings"]),
                 (" (%d blocking)" % len(blocking)) if blocking else ""))
        for f in outcome["findings"][:args.show]:
            print("  [%-8s] %s: %s: %s" % (f["severity"], f["rule"], f.get("node") or "(graph)", f["message"]))
        if blocking and args.strict:
            print("\nblocking policy findings on the live graph: errors under --strict.")
            return 1

    strict = False
    strict_attributes = False
    try:
        with open(project.ontology_config_path, encoding="utf-8") as f:
            cfg = _json.load(f)
            strict = bool(cfg.get("strict_domains"))
            strict_attributes = bool(cfg.get("strict_attributes"))
    except Exception:
        pass
    if attrs["mistyped"] or (strict_attributes and attrs["undeclared"]):
        print("\nattribute values contradict their declarations: errors.")
        return 1
    if strict and (report["domain_violations"] or report["range_violations"]):
        print("\nstrict_domains is on: the violations above are errors.")
        return 1
    # A breaking change is fine when the version was bumped: that IS the acknowledgement. Strict
    # mode objects only to a breaking change nobody declared.
    if args.strict and unacknowledged:
        return 1
    return 0


def register(sub):
    ontology = sub.add_parser("ontology", help="the project's vocabulary, and the catalog of ontologies to start from")
    ontology.add_argument("ontology_command", nargs="?", default="check",
                          choices=["check", "accept", "rationale", "widen", "import"] + list(_catalog.VERBS),
                          help="on the project's own vocabulary: check (default) reports changes and conformance; "
                               "accept records it as the baseline; rationale reports whether each class has a "
                               "recorded reason and who confirmed it; widen proposes what the data uses; import "
                               "merges a file or a named ontology into it. On the catalog: list, show <name>, "
                               "export --name, add <name|name@release|url>, update [<name>], diff against what "
                               "this project started from, publish --to <registry>")
    project_arguments(ontology)
    ontology.add_argument("--show", type=int, default=8, help="how many mismatch patterns to list")
    ontology.add_argument("--file", default=None,
                          help="for import: a vocabulary as .ttl (as OTO emits it), .csv or .json")
    ontology.add_argument("--from", dest="from_name", default=None,
                          help="for import: an ontology name, or several comma-separated to merge; for publish: "
                               "publish this ontology from this machine instead of exporting the project")
    ontology.add_argument("--replace", action="store_true",
                          help="for import: overwrite classes and relations already declared")
    ontology.add_argument("--strict", action="store_true",
                          help="exit non-zero on a breaking change with no version bump")
    ontology.add_argument("--frequent", type=int, default=5,
                          help="how often a pattern must occur before `widen` treats it as real usage "
                               "rather than a mistake in the data (default 5)")
    _catalog.options(ontology)
    ontology.set_defaults(func=cmd_ontology)
