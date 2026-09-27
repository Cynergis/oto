# -*- coding: utf-8 -*-
"""`oto curate`: propose, review and apply changes to the curated graph."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_curate(args):
    import json as _json

    from ..curate import diff as _diff, session as _session
    from ..validate import privacy as _privacy

    project = _resolve(args)
    command = args.curate_command

    if command == "start":
        try:
            path = _session.start(project, force=args.force)
        except FileExistsError as exc:
            print("oto: a candidate already exists at %s. Edit it, or `oto curate abort` first, or "
                  "pass --force." % os.path.basename(str(exc)), file=sys.stderr)
            return 1
        print("candidate created: %s" % os.path.relpath(path, os.path.dirname(project.src)))
        print("Edit it, then run `oto curate check`. The live graph is untouched until you apply.")
        return 0

    if command == "add":
        from ..curate import batch as _batch
        from ._common import today as _today

        if not args.source:
            print("oto: add needs --from <proposal.json> (repeatable)", file=sys.stderr)
            return 1
        if not _session.exists(project):
            print("oto: no candidate. Run `oto curate start` first.", file=sys.stderr)
            return 1
        graph = _session.candidate(project)
        reports = []
        for path in args.source:
            try:
                proposal = _batch.load(path)
            except (OSError, ValueError) as exc:
                print("oto: cannot read %s: %s" % (path, exc), file=sys.stderr)
                return 1
            graph, report = _batch.merge(graph, proposal, _today())
            reports.append((path, report))

        refusals = []
        for path, report in reports:
            for reason in _batch.refused(report):
                refusals.append("%s: %s" % (os.path.basename(path), reason))
        if refusals:
            print("%s the batch; nothing written:" % ("would refuse" if args.dry_run else "refusing"))
            for reason in refusals[:args.show * 2]:
                print("  %s" % reason)
            return 1

        if not args.dry_run:
            _session._write(_session.candidate_path(project), graph)
        verb = "would add" if args.dry_run else "+"
        for path, report in reports:
            print("%s: %s%d node(s), %d merged, %d updated, %s%d edge(s) (%d already present)"
                  % (os.path.basename(path), verb + " " if args.dry_run else verb, len(report["added"]),
                     len(report["merged"]), len(report["updated"]),
                     verb + " " if args.dry_run else verb, report["edges_added"], report["edges_existing"]))
            for nid, fields in report["updated"][:args.show]:
                print("    updated  %-28s %s" % (nid, ", ".join(fields)))
            for nid, others in report["suspects"][:args.show]:
                print("    SUSPECT  %-28s same name as %s: one entity or two?" % (nid, ", ".join(others)))
            if report["edges_dangling"]:
                print("    %d edge(s) point at a node not in the candidate yet; `oto curate check` "
                      "blocks until it arrives" % len(report["edges_dangling"]))
        if args.dry_run:
            print("dry run: the candidate is unchanged. Drop --dry-run to merge.")
        else:
            print("candidate now has %d node(s), %d edge(s). Next: oto curate check."
                  % (len(graph["nodes"]), len(graph["edges"])))
        return 0

    if command == "abort":
        print("candidate discarded" if _session.abort(project) else "no candidate to discard")
        return 0

    if command == "assert":
        from ..curate import assertions as _assertions

        if not args.text:
            print("oto: --text is required for an assertion", file=sys.stderr)
            return 1
        try:
            entry = _assertions.record(project, text=args.text, by=args.by, at=args.at,
                                       about=[x for x in (args.about or "").split(",") if x.strip()])
        except ValueError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("recorded %s" % entry["id"])
        print("  by   %s" % entry["by"])
        print("  at   %s" % entry["at"])
        print("  text %s" % entry["text"][:100])
        print("\nCite it from any fact you derive:")
        print('  "source_type": "human_assertion", "sources": ["%s"]'
              % _assertions.reference(entry["id"]))
        print("\nThe log is append-only. Nothing has entered the graph yet: edit the candidate, then")
        print("`oto curate check`.")
        return 0

    if command == "assertions":
        from ..curate import assertions as _assertions

        entries = _assertions.read(project)
        if not entries:
            print("no assertions recorded")
            return 0
        print("%d assertion(s) on record:" % len(entries))
        for entry in entries[-args.show:]:
            print("  %-8s %-12s %-28s %s" % (entry.get("id"), entry.get("at"),
                                             (entry.get("by") or "")[:28],
                                             (entry.get("text") or "")[:60]))
        counts = _assertions.summarize(_session.live(project).get("nodes") or [])
        print("\nhow the graph's facts are sourced:")
        for kind in ("document", "human_assertion", "inference", "unrecorded"):
            print("  %-16s %d" % (kind, counts[kind]))
        return 0

    if command == "resolve":
        if not args.term:
            print("oto: resolve needs --term <words>", file=sys.stderr)
            return 1
        graph = _session.candidate(project) if _session.exists(project) else _session.live(project)
        live_ids = {n.get("id") for n in _session.live(project).get("nodes") or []}
        matches = _session.find(graph, args.term)
        where = "candidate" if _session.exists(project) else "live graph"
        if not matches:
            print("%r: nothing in the %s. A new id is warranted; derive it from the label." % (args.term, where))
            return 0
        print("%r in the %s:" % (args.term, where))
        for node in matches[:args.show]:
            tag = "" if node.get("id") in live_ids else "  (candidate only: not built yet)"
            print("  %-30s %-14s %-32s [%s]%s" % (node.get("id"), node.get("type"),
                                                  (node.get("label") or "")[:32],
                                                  node.get("status", "current"), tag))
        if len(matches) > args.show:
            print("  ... and %d more" % (len(matches) - args.show))
        print("Reuse the id; a second id for the same thing is how a graph rots.")
        return 0

    if command == "log":
        from ..curate import ledger as _ledger

        print(_ledger.render(_ledger.read(project), limit=args.show))
        return 0

    if command == "undo":
        restored = _session.undo(project)
        if not restored:
            print("nothing to undo")
            return 1
        print("restored the previous graph. Run `oto build` to recompile.")
        return 0

    if not _session.exists(project):
        print("oto: no candidate. Run `oto curate start` first.", file=sys.stderr)
        return 1

    live = _session.live(project)
    proposed = _session.candidate(project)
    summary = _diff.summarize(live, proposed)

    print("candidate would change the graph:")
    print("  nodes: +%d  -%d  ~%d" % (len(summary["nodes_added"]), len(summary["nodes_removed"]),
                                      len(summary["nodes_changed"])))
    print("  edges: +%d  -%d" % (len(summary["edges_added"]), len(summary["edges_removed"])))
    reprovenanced = summary.get("nodes_reprovenanced") or []
    if reprovenanced:
        print("  provenance changed on %d node(s): the facts are the same, who attests them is not"
              % len(reprovenanced))
    for label, items in (("added", summary["nodes_added"]), ("removed", summary["nodes_removed"])):
        for nid in items[:args.show]:
            print("    node %-8s %s" % (label, nid))
        if len(items) > args.show:
            print("    ... and %d more %s" % (len(items) - args.show, label))
    for nid, fields in summary["nodes_changed"][:args.show]:
        print("    node changed  %-28s (%s)" % (nid, ", ".join(fields)))
    for nid, fields in reprovenanced[:args.show]:
        print("    provenance    %-28s (%s)" % (nid, ", ".join(fields)))
    if len(reprovenanced) > args.show:
        print("    ... and %d more provenance change(s)" % (len(reprovenanced) - args.show))
    for key in summary["edges_added"][:args.show]:
        print("    edge added    %s -%s-> %s" % key)
    for key in summary["edges_removed"][:args.show]:
        print("    edge removed  %s -%s-> %s" % key)

    if command == "diff":
        return 0

    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = _json.load(f)
    from ..curate import assertions as _assertions
    findings = _diff.check(live, proposed, vocabulary, known_assertions=_assertions.known_ids(project))

    from ..reason import engine as _engine, rules as _rules
    declared_rules = _rules.load(project)
    if declared_rules and not _rules.problems(declared_rules, vocabulary):
        try:
            outcome = _engine.run(declared_rules, proposed.get("nodes") or [], proposed.get("edges") or [])
        except _engine.DoesNotConverge as exc:
            findings.append(_diff.Finding(_diff.Finding.BLOCKING, "rules", str(exc)))
        else:
            for item in outcome["findings"]:
                severity = _diff.Finding.BLOCKING if item["severity"] == "blocking" else _diff.Finding.GAP
                findings.append(_diff.Finding(severity, item.get("node") or "(graph)",
                                              "policy %s: %s" % (item["rule"], item["message"])))
    from ..curate import reattest as _reattest
    for item in _reattest.pending(project, proposed):
        findings.append(_diff.Finding(
            _diff.Finding.GAP, item["id"],
            "cites %s, which arrived as a new version on %s (run %s): list it in that document's "
            "proposal to re-attest it, or retire it" % (item["slug"], item["since"], item["run_id"])))
    privacy_findings = _privacy.scan(_diff.authored_text(proposed, live))
    hard_privacy = _privacy.blocking(privacy_findings)

    groups = {}
    for finding in findings:
        groups.setdefault(finding.severity, []).append(finding)
    for severity in (_diff.Finding.BLOCKING, _diff.Finding.CONTRADICTION, _diff.Finding.GAP):
        items = groups.get(severity) or []
        if not items:
            continue
        print("\n%s (%d):" % (severity, len(items)))
        for finding in items[:args.show]:
            print("  %-34s %s" % (finding.subject, finding.detail))
        if len(items) > args.show:
            print("  ... and %d more" % (len(items) - args.show))

    if privacy_findings:
        print("\nprivacy scan of the text this change introduces:")
        print(_privacy.summarize(privacy_findings))

    blocked = _diff.blocking(findings)
    if hard_privacy and not args.allow_personal_data:
        blocked = blocked + [None] * len(hard_privacy)

    if command == "check":
        if blocked:
            print("\n%d blocking problem(s). Fix them, then check again." % len(blocked))
            return 1
        if groups.get(_diff.Finding.CONTRADICTION):
            print("\nNo blocking problems, but a fact changed with no supersession record. Read those "
                  "before applying: overwriting destroys the answer to what was true before.")
        print("\nready to apply" if not groups.get(_diff.Finding.CONTRADICTION)
              else "\nready to apply once the contradictions above are deliberate")
        return 0

    if command == "apply":
        if blocked and not args.force:
            print("\n%d blocking problem(s). Refusing to apply." % len(blocked))
            return 1
        from ..curate import ledger as _ledger
        from ..intake import pipeline as _pipeline

        retired = _ledger.retirements(live, proposed)
        record = _ledger.entry(summary, retired, by=args.by, note=args.note,
                               runs=[m["run_id"] for m in _pipeline.open_runs(project)],
                               sources=_ledger.new_sources(live, proposed))
        result = _session.apply(project)
        _ledger.append(project, record)
        print("\napplied. Previous graph kept at %s; `oto curate undo` restores it."
              % os.path.basename(result["previous"]))
        print("ledger: %s (%d retired). `oto curate log` reads it." % (_ledger.NAME, len(retired)))
        if not args.note:
            print("  no --note: say what this made answerable and what it left open, next time.")
        print("Run `oto build` to recompile.")
        return 0

    return 0


def register(sub):
    curate = sub.add_parser("curate", help="propose, review and apply changes to the curated graph")
    curate.add_argument("curate_command", nargs="?", default="check",
                        choices=["start", "add", "diff", "check", "apply", "abort", "undo",
                                 "assert", "assertions", "log", "resolve"],
                        help="start a candidate; add merges proposal files into it; diff shows what it changes; check validates it; "
                             "apply promotes it (with --by and --note for the ledger); abort discards it; undo restores the previous graph; log reads the ledger; "
                             "assert records something a person said; assertions lists them")
    curate.add_argument("--from", dest="source", action="append", default=None,
                        help="a proposal file of nodes and edges, for `add` (repeatable)")
    curate.add_argument("--text", default=None, help="the statement, for `assert`")
    curate.add_argument("--by", default=None,
                        help="who said it (assert), or who applied it (apply): an unattributed change cannot be followed up")
    curate.add_argument("--at", default=None,
                        help="the date it refers to, as YYYY-MM-DD. Never defaulted: a correction "
                             "usually refers to when something became true, not when it was typed")
    curate.add_argument("--about", default=None, help="comma-separated node ids this is about")
    curate.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="for add: report what the merge would do, and refuse what it would refuse, "
                             "without writing the candidate")
    curate.add_argument("--term", default=None,
                        help="for resolve: a label, alias or id to look up in the candidate")
    curate.add_argument("--note", default=None,
                        help="for apply: what this change made answerable, what it left open; kept in the ledger")
    project_arguments(curate)
    curate.add_argument("--show", type=int, default=10, help="how many items to list per section")
    curate.add_argument("--force", action="store_true",
                        help="overwrite an existing candidate, or apply despite blocking problems")
    curate.add_argument("--allow-personal-data", action="store_true",
                        help="apply even when the privacy scan finds blocking items")
    curate.set_defaults(func=cmd_curate)
