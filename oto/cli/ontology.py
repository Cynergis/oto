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

    if args.ontology_command == "capture" and args.from_name:
        # the capture schema of a pack needs no project
        from ..compile import capture as _capture
        try:
            schema = _capture.for_ontology(args.from_name)
        except (KeyError, ValueError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        out = args.file or os.path.join(os.getcwd(), "capture.json")
        _capture.write(out, schema)
        print("capture schema of %s: %s  (%d section(s), %d question(s), %d type(s))" % (
            args.from_name, out, len(schema["sections"]), sum(len(s["asks"]) for s in schema["sections"]), len(schema["types"])))
        return 0

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
        carried_rules, carried_questions = [], {}
        try:
            if args.from_name:
                names = [t.strip() for t in args.from_name.split(",") if t.strip()]
                for one in names:
                    if _ontologies.dir_for(one) is None:
                        raise ValueError("unknown ontology %r. Available: %s"
                                         % (one, ", ".join(_ontologies.available()) or "none"))
                if len(names) == 1:
                    composed = _ontologies.composed(names[0])
                    config = composed["config"]
                    classes, properties = config["classes"], config["properties"]
                    rationale = composed["rationale"]
                    carried_rules, carried_questions = composed["rules"], composed["questions"]
                    notes = []
                else:
                    config, _sample, _readme, rationale, report = _ontologies.merge(names)
                    classes, properties = config["classes"], config["properties"]
                    carried_rules = list(config.pop("_rules", None) or [])
                    carried_questions = dict(config.pop("_questions", None) or {})
                    for key in ("_lexicon", "_interview", "_guide", "_actions", "_gold"):
                        config.pop(key, None)
                    notes = ["class %s: described differently in %s and %s; kept %s" % (k, a, b, a)
                             for k, a, b in report["class_clashes"]]
                    notes += ["relation %s: domain or range differ in %s and %s; widened to both" % (r, a, b)
                              for r, a, b in report["relation_clashes"]]
                    notes.append("merged %d ontologies; prune before accepting" % len(names))
                attributes = config.get("attributes") or {}
                namespaces, schemes = config.get("namespaces"), config.get("schemes")
            else:
                classes, properties, notes = _importer.read(args.file)
                attributes, schemes = _importer.read.attributes, _importer.read.schemes
                namespaces = _importer.read.namespaces
                if _importer.read.rationale and any(_importer.read.rationale.values()):
                    rationale = _importer.read.rationale
            problems = _importer.check(classes, properties, attributes, schemes)
            if problems:
                print("the vocabulary is not usable as read:")
                for problem in problems[:args.show * 2]:
                    print("  %s" % problem)
                return 1
            path = _importer.apply(project, classes, properties, rationale=rationale, replace=args.replace,
                                   attributes=attributes, namespaces=namespaces, schemes=schemes)
        except (OSError, ValueError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("wrote %d class(es), %d relation(s) and %d attribute declaration(s) to %s"
              % (len(classes), len(properties), sum(len(v) for v in attributes.values()), os.path.basename(path)))
        # The rules and the questions an ontology ships come with its vocabulary: merged by id into
        # what the project already declares, so a project's own stay and the ontology's are added.
        from ..reason import rules as _rules, questions as _questions
        if carried_rules:
            own = _rules.load(project)
            have = {r.get("id") for r in own if isinstance(r, dict)}
            added = [r for r in carried_rules if r.get("id") not in have]
            if added or not own:
                _rules.save(project, own + added)
            print("  rules: %d carried, %d added to %s" % (len(carried_rules), len(added), _rules.NAME))
        if carried_questions:
            own = _questions.load(project)
            added = {k: v for k, v in carried_questions.items() if k not in own}
            if added or not own:
                _questions.save(project, dict(own, **added))
            print("  questions: %d carried, %d added to %s" % (len(carried_questions), len(added), _questions.NAME))
        for note in notes:
            print("  note: %s" % note)
        if rationale:
            print("  rationale carried over; validated_by is not a confirmation for this domain")
        else:
            print("  no rationale came with it: every class now lacks a recorded reason. Run the "
                  "ontology-interview skill, then `oto ontology rationale --strict`.")
        print("  then: oto ontology check, and oto ontology accept")
        return 0

    if args.ontology_command == "capture":
        from ..compile import capture as _capture
        schema = _capture.for_project(project)
        out = args.file or os.path.join(project.data, "capture.json")
        _capture.write(out, schema)
        print("capture schema: %s  (%d section(s), %d question(s), %d type(s))" % (
            out, len(schema["sections"]), sum(len(s["asks"]) for s in schema["sections"]), len(schema["types"])))
        print("  a tool fills it as items of a type with fields and links; `oto curate propose --from <capture>` turns them into a proposal")
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
        from ..reason import rules as _rules, questions as _questions
        with open(project.ontology_config_path, encoding="utf-8") as f:
            declared_config = _json.load(f)
        declared_questions = _questions.load(project)
        refusals = _questions.problems(declared_questions, declared_config)
        if not refusals:
            refusals = ["no question cites %s" % term for term in _questions.uncovered(declared_questions, declared_config)]
        if refusals:
            print("oto: refusing to accept a vocabulary whose questions do not cover it; every class, relation and "
                  "attribute exists to answer a question that runs (questions.json):")
            for problem in refusals[:args.show * 2]:
                print("  %s" % problem)
            if len(refusals) > args.show * 2:
                print("  ... and %d more" % (len(refusals) - args.show * 2))
            return 1
        path = vocab.write_lock(project, current, rules=_rules.load(project), questions=declared_questions)
        print("accepted vocabulary version %d (%d classes, %d relations, %d rules, %d questions)"
              % (current.version, len(current.classes), len(current.properties), len(_rules.load(project)),
                 len(declared_questions)))
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
        changes = vocab.impact(vocab.diff(locked, current), nodes, edges, current)
        if not changes:
            print("\nno change since version %d was accepted" % locked.version)
        else:
            print("\n%d change(s) since version %d was accepted:" % (len(changes), locked.version))
            for change in changes:
                touches = (" — touches %d" % change.affected) if change.affected else ""
                print("  [%-9s] %-28s %-24s %s%s"
                      % (change.severity, change.kind, change.subject, change.detail, touches))
            from ..model import rationale as _rationale
            for kind, name, by in vocab.reconfirm(locked, current, _rationale.load(project)):
                print("  RECONFIRM %s %s: its definition changed since %s confirmed it; ask them again, "
                      "or clear validated_by" % (kind, name, by))
            breaking = sum(1 for c in changes if c.severity == vocab.Change.BREAKING)
            if breaking and current.version <= locked.version:
                unacknowledged = breaking
                print("\n%d breaking change(s) with no version bump. Raise `ontology_version` in "
                      "ontology.config.json, then run `oto ontology accept`." % breaking)
            elif breaking:
                unacknowledged = 0
                print("\n%d breaking change(s), acknowledged by the bump to version %d. Run "
                      "`oto ontology accept` to record it." % (breaking, current.version))

    with open(project.ontology_config_path, encoding="utf-8") as f:
        _declared_languages = _json.load(f).get("languages")
    if _declared_languages:
        for kind, declared in current.attributes.items():
            for name, spec in declared.items():
                if str(spec.get("type", "")).startswith("enum:"):
                    print("  note: attribute %s.%s is an enum, so its values carry no label in %s; declare a scheme "
                          "if people ask what they mean" % (kind, name, ", ".join(_declared_languages)))

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
        from ..reason.questions import declared_names
        outcome = _engine.run(declared_rules, nodes, edges, covers=vocab.covers(current.classes),
                              declared=declared_names(_json.load(open(project.ontology_config_path, encoding="utf-8"))))
        blocking = [f for f in outcome["findings"] if f["severity"] == "blocking"]
        print("\nrules: %d declared; %d edge(s) and %d attribute(s) would be derived; %d policy finding(s)%s"
              % (len(declared_rules), len(outcome["edges"]), len(outcome["attributes"]), len(outcome["findings"]),
                 (" (%d blocking)" % len(blocking)) if blocking else ""))
        for f in outcome["findings"][:args.show]:
            print("  [%-8s] %s: %s: %s" % (f["severity"], f["rule"], f.get("node") or "(graph)", f["message"]))
        if blocking and args.strict:
            print("\nblocking policy findings on the live graph: errors under --strict.")
            return 1

    from ..reason import shapes as _shapes
    with open(project.ontology_config_path, encoding="utf-8") as f:
        shape_config = _json.load(f)
    shape_problems = _shapes.problems(shape_config)
    if shape_problems:
        print("\nshapes are not usable:")
        for problem in shape_problems[:args.show]:
            print("  %s" % problem)
        return 1
    shape_findings = _shapes.findings(shape_config, nodes, edges)
    declared_shapes = _shapes.declared(shape_config)
    if declared_shapes:
        print("\nshapes: %d declared (%s); %s" % (
            len(declared_shapes), ", ".join("%d %s" % (sum(1 for s in declared_shapes if s["kind"] == k), k)
                                            for k in ("min", "max", "required", "requires") if any(s["kind"] == k for s in declared_shapes)),
            "every node satisfies them" if not shape_findings else "%d violation(s) on the live graph:" % len(shape_findings)))
        for item in shape_findings[:args.show]:
            print("  [%-8s] %s" % (item["kind"], item["message"]))
    else:
        print("\nshapes: none declared (no min, max, required or requires in the vocabulary)")

    from ..reason import questions as _questions
    declared_questions = _questions.load(project)
    question_findings, uncovered = [], []
    with open(project.ontology_config_path, encoding="utf-8") as f:
        declared_config = _json.load(f)
    question_problems = _questions.problems(declared_questions, declared_config)
    if question_problems:
        print("\nquestions.json is not usable:")
        for problem in question_problems[:args.show]:
            print("  %s" % problem)
        return 1
    uncovered = _questions.uncovered(declared_questions, declared_config)
    if declared_questions:
        entries = _questions.survey(declared_questions, nodes, edges, vocab.covers(current.classes),
                                    declared=_questions.declared_names(declared_config))
        question_findings = [e for e in entries if e["status"] in _questions.FINDING_STATUSES]
        print("\nquestions: %d declared; the live graph answers %d as required%s"
              % (len(entries), len(entries) - len(question_findings),
                 (", %d it cannot:" % len(question_findings)) if question_findings else ""))
        for e in question_findings[:args.show]:
            first = (e["unanswered"] or [{"label": "(graph)", "gaps": e["gaps"]}])[0]
            print("  %-6s %-11s %s%s%s" % (e["id"], e["status"], e["question"],
                                            (": " + first["label"]) if e["unanswered"] else "",
                                            ("; " + "; ".join(first["gaps"])) if first["gaps"] else ""))
        locked_questions = _questions.read_lock(project)
        if locked_questions is not None:
            added, removed, changed, reworded = _questions.diff(locked_questions, declared_questions)
            for qid in removed:
                print("  [breaking ] question removed   %s: what the graph answered is no longer asked" % qid)
            for qid in changed:
                print("  [breaking ] question changed   %s: its ask, params or gate differ; it is a different question" % qid)
            for qid in added:
                print("  [additive ] question added     %s" % qid)
            for qid in reworded:
                print("  [cosmetic ] question reworded  %s" % qid)
    else:
        print("\nquestions: none declared (questions.json absent or empty)")
    if uncovered:
        print("  %d term(s) no question cites: %s%s" % (len(uncovered), ", ".join(uncovered[:args.show]),
                                                         " ..." if len(uncovered) > args.show else ""))
        print("  A term no question needs is a term nobody can tell the purpose of. `oto ontology accept` refuses it.")

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
    if args.strict and (question_findings or uncovered or shape_findings):
        print("\nshape violations, questions the graph cannot answer, or terms no question cites: errors under --strict.")
        return 1
    # A breaking change is fine when the version was bumped: that IS the acknowledgement. Strict
    # mode objects only to a breaking change nobody declared.
    if args.strict and unacknowledged:
        return 1
    return 0


def register(sub):
    ontology = sub.add_parser("ontology", help="the project's vocabulary, and the catalog of ontologies to start from")
    ontology.add_argument("ontology_command", nargs="?", default="check",
                          choices=["check", "accept", "rationale", "widen", "import", "capture"] + list(_catalog.VERBS),
                          help="on the project's own vocabulary: check (default) reports changes and conformance; capture writes capture.json, what a tool asks for; "
                               "accept records it as the baseline; rationale reports whether each class has a "
                               "recorded reason and who confirmed it; widen proposes what the data uses; import "
                               "merges a file or a named ontology into it. On the catalog: list, show <name>, "
                               "export --name, add <name|name@release|url>, update [<name>], diff against what "
                               "this project started from, publish --to <registry>")
    project_arguments(ontology)
    ontology.add_argument("--show", type=int, default=8, help="how many mismatch patterns to list")
    ontology.add_argument("--file", default=None,
                          help="for import: an ontology (.ttl, .rdf, .owl, .jsonld, .nt; any OWL/RDFS/SKOS, with the rdf extra), or a .csv or .json vocabulary")
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
