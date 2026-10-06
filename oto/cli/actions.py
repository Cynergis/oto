# -*- coding: utf-8 -*-
"""`oto actions`: list, check and show the actions a project declares, with their readiness
against the authored graph and their inputs bound to one entity; record a run the caller
performed, so its response becomes evidence through the gates; list the runs. OTO never invokes
one."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def _graph(project):
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    return list(graph.get("nodes") or []), list(graph.get("edges") or [])


def cmd_actions(args):
    from ..actions import model as _model

    project = _resolve(args)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    from ..model.vocabulary import covers as _covers
    covers = _covers(vocabulary.get("classes") or {})
    loaded = _model.load(project)
    problems = _model.problems(loaded, vocabulary)

    if args.actions_command == "check":
        if not loaded:
            print("no actions declared (no actions/*.json)")
            return 0
        if problems:
            print("%d problem(s) in actions/:" % len(problems))
            for problem in problems:
                print("  %s" % problem)
            return 1
        print("%d action(s) usable" % len(loaded))
        for _rel, action, _error in loaded:
            print("  %-36s %-8s %-10s %s" % (action["id"], "read" if _model.read_only(action) else "CHANGE",
                                             action["invoke"]["transport"], action["subject"]))
        return 0

    from ..actions import catalog as _catalog, runs as _runs
    usable = _catalog.with_last_runs([action for _rel, action, error in loaded if not error and action.get("id")],
                                       _runs.last_runs(project))

    if args.actions_command == "runs":
        records = _runs.all_runs(project)
        if not records:
            print("no runs recorded. `oto actions record <action> --on <entity> --by <you> --response <file>` records one.")
            return 0
        if args.json:
            print(json.dumps([dict(rec, directory=rel) for rel, rec in records], indent=2, ensure_ascii=False))
            return 0
        print("%d run(s), oldest first:" % len(records))
        for rel, rec in records:
            print("  %s  %-34s on %-24s by %-16s %s%s -> %s" % (
                rec.get("at"), rec["action"], rec["on"], rec.get("by"), rec.get("result_kind"),
                "" if rec.get("ready", True) else " (not ready)", rec.get("proposal") or rec.get("document")))
        return 0

    if args.actions_command == "record":
        return _record(args, project, usable)

    if args.actions_command == "show":
        if not args.which:
            print("oto: show needs an action id: oto actions show <action.id> [--on <entity id>]", file=sys.stderr)
            return 2
        action = next((a for a in usable if a["id"] == args.which[0]), None)
        if action is None:
            print("oto: no action %r; declared: %s" % (args.which[0], ", ".join(a["id"] for a in usable) or "none"), file=sys.stderr)
            return 1
        nodes, edges = _graph(project)
        subject = None
        if args.on:
            subject = next((n for n in nodes if n.get("id") == args.on), None)
            if subject is None:
                print("oto: no entity %r in graph.json (an id, exactly)" % args.on, file=sys.stderr)
                return 1
            if subject.get("type") != action.get("subject"):
                print("oto: %s is a %s; %s acts on %s" % (args.on, subject.get("type"), action["id"], action.get("subject")), file=sys.stderr)
                return 1
        definition = _catalog.tool_definition(action, nodes, edges, on=subject, covers=covers)
        if args.json:
            print(json.dumps(definition, indent=2, ensure_ascii=False))
        else:
            print(_catalog.text([definition], heading="%s: the invocation the caller performs (OTO does not):" % action["id"]))
        return 0

    # list
    if not loaded:
        print("no actions declared. An action is a file actions/<id>.json; `oto actions check` validates them.")
        return 0
    nodes, edges = _graph(project)
    definitions = _catalog.catalog(usable, nodes, edges, ready_only=args.ready, due_only=args.due, covers=covers)
    if args.json:
        print(json.dumps(definitions, indent=2, ensure_ascii=False))
        return 0
    if problems:
        print("%d problem(s) in actions/ (oto actions check); listing what is readable." % len(problems))
    for rel, _action, error in loaded:
        if error:
            print("  %-36s unreadable: %s" % (rel, error))
    if args.due and not definitions:
        print("No scheduled read-only action is due and ready; `oto actions list` says when each runs next.")
        return 0
    if args.ready and not definitions:
        print("No action is ready on the authored graph; `oto actions list` says why for each.")
        return 0
    print(_catalog.text(definitions))
    return 0


def _record(args, project, usable):
    from ..actions import catalog as _catalog, runs as _runs
    from ._common import today as _today

    if not args.which or not args.on or not args.response:
        print("oto: record needs an action, an entity and a response: "
              "oto actions record <action.id> --on <entity id> --by <you> --response <file|->", file=sys.stderr)
        return 2
    action = next((a for a in usable if a["id"] == args.which[0]), None)
    if action is None:
        print("oto: no action %r; declared: %s" % (args.which[0], ", ".join(a["id"] for a in usable) or "none"), file=sys.stderr)
        return 1
    nodes, edges = _graph(project)
    subject = next((n for n in nodes if n.get("id") == args.on), None)
    if subject is None:
        print("oto: no entity %r in graph.json (an id, exactly)" % args.on, file=sys.stderr)
        return 1
    if subject.get("type") != action.get("subject"):
        print("oto: %s is a %s; %s acts on %s" % (args.on, subject.get("type"), action["id"], action.get("subject")), file=sys.stderr)
        return 1
    if args.response == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(args.response, encoding="utf-8") as f:
                raw = f.read()
        except OSError as exc:
            print("oto: cannot read the response: %s" % exc, file=sys.stderr)
            return 1
    try:
        response = json.loads(raw)
    except ValueError:
        response = raw
    if (action.get("result") or {}).get("kind") == "proposal" and not isinstance(response, dict):
        print("oto: %s renders a proposal from the response, which must be a JSON object; got %s"
              % (action["id"], "text" if isinstance(response, str) else type(response).__name__), file=sys.stderr)
        return 1
    from ..model.vocabulary import covers as _covers
    with open(project.ontology_config_path, encoding="utf-8") as f:
        covers = _covers((json.load(f).get("classes") or {}))
    ready, _reason = _catalog.readiness(action, nodes, edges, covers)
    inputs, missing = _catalog.bind(action, subject)
    try:
        rec = _runs.record(project, action, subject, response, args.by or "", args.at or _today(),
                           ready=args.on in ready, inputs=inputs, inputs_missing=missing, note=args.note)
    except ValueError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    print("recorded %s on %s by %s at %s -> %s" % (action["id"], subject["id"], rec["by"], rec["at"], rec["directory"]))
    if not rec["ready"]:
        print("  note: the action's preconditions did not hold on this entity; recorded as such")
    print("  document: %s   (a source: `oto ingest --project %s` brings it into the corpus)" % (rec["document"], project.data))
    if rec.get("withheld"):
        print("  no proposal: %s" % rec["withheld"])
    if rec["proposal"]:
        print("  proposal: %s" % rec["proposal"])
        for path in rec["unresolved"]:
            print("  unresolved: %s (not in the response; left out)" % path)
        print("  next: oto curate start, then oto curate add --project %s --from %s --dry-run, check, apply, build"
              % (project.data, os.path.join(project.data, rec["proposal"])))
    elif not rec.get("withheld"):
        print("  next: oto ingest, then author the proposal from the document (the build-knowledge-base skill)")
    return 0


def register(sub):
    actions = sub.add_parser("actions", help="list and check the actions the project declares (OTO never invokes one)")
    actions.add_argument("actions_command", nargs="?", default="list", choices=["list", "check", "show", "record", "runs"],
                         help="list prints every action with its readiness on the authored graph; check validates the "
                              "files against the vocabulary; show <id> [--on <entity>] prints one as the MCP tool "
                              "definition the caller invokes, inputs bound to the entity; record <id> --on <entity> "
                              "--by <you> --response <file|-> writes the run the caller performed as a source document "
                              "and, for a proposal result, the proposal; runs lists the records")
    actions.add_argument("which", nargs="*", help="for show and record: the action id")
    project_arguments(actions)
    actions.add_argument("--on", default=None, metavar="ENTITY", help="for show and record: the subject entity's id")
    actions.add_argument("--by", default=None, help="for record: who performed the invocation (required)")
    actions.add_argument("--at", default=None, metavar="YYYY-MM-DD", help="for record: the date of the invocation (default today)")
    actions.add_argument("--response", default=None, metavar="FILE", help="for record: the response the invocation returned, a file or - for stdin")
    actions.add_argument("--note", default=None, help="for record: a note kept with the run")
    actions.add_argument("--ready", action="store_true", help="for list: only the actions ready on at least one entity")
    actions.add_argument("--due", action="store_true", help="for list: only the scheduled read-only actions whose run is due and that are ready")
    actions.add_argument("--json", action="store_true", help="the tool definitions as JSON")
    actions.set_defaults(func=cmd_actions)
