# -*- coding: utf-8 -*-
"""`oto factory`: the factory's inputs read from the graph. spec projects a component's spec,
schema-checked and hashed (roadmap I3); plan derives the build order from contract dependencies (I5);
scope writes the run snapshot the factory plugin's hooks enforce (J2); run keeps a run's own graph and
promotes its results (I8, J4); criteria draws the acceptance criteria from the graph (I6); deviate records
a deviation as a change proposal (I7, H5)."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_factory(args):
    from .. import factory as _factory
    from ..curate import session as _session
    project = None if args.factory_command in ("run", "deviate") else _resolve(args)
    if args.factory_command == "spec":
        if args.check:
            if not os.path.isfile(args.check):
                print("oto: no such spec: %s" % args.check, file=sys.stderr)
                return 1
            with open(args.check, encoding="utf-8") as f:
                try:
                    doc = json.load(f)
                except ValueError as exc:
                    print("oto: %s is not JSON: %s" % (args.check, exc), file=sys.stderr)
                    return 1
            problems = _factory.verify_spec(doc)
            if problems:
                print("oto: %s is not a spec the graph wrote:" % args.check, file=sys.stderr)
                for p in problems:
                    print("  %s" % p, file=sys.stderr)
                return 1
            print("%s holds: the shape is a spec's and the hash is its content's" % args.check)
            return 0
        if not args.component:
            print("oto: spec takes the component (component.<id>), or --check <file>", file=sys.stderr)
            return 1
        try:
            doc = _factory.spec(_session.live(project), args.component, at=args.at)
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("%s: the spec of %s, %d exposed, %d consumed, %d requirement(s); check it with oto factory spec --check %s" % (
                args.out, doc["component"]["label"], len(doc["exposes"]), len(doc["consumes"]), len(doc["requirements"]), args.out))
        else:
            sys.stdout.write(text)
        return 0
    if args.factory_command == "plan":
        graph = _session.live(project)
        try:
            if args.all:
                ids, contexts = _factory.components_for(graph, "all")
            else:
                ids, contexts = _factory.components_for(graph, "ready", context=args.context)
            result = _factory.plan(graph, ids)
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        result["contexts"] = contexts
        nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
        result["labels"] = {cid: nodes.get(cid, {}).get("label") or cid for cid in result["components"]}
        if args.json:
            text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        elif not ids and not args.all and not args.context:
            text = ("no context is ready: nothing to build. A named person signs off a context with "
                    "`oto decide <context> readiness=ready --by <name> --at <date>`; `oto factory plan --all` plans every CALM component regardless.\n")
        else:
            text = _factory.render_plan(result, nodes)
            if contexts:
                text = "for context(s) %s:\n" % ", ".join(contexts) + text
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("%s: %d build(s) in %d group(s)" % (args.out, len(result["components"]) - len(result["unplanned"]), len(result["groups"])))
        else:
            sys.stdout.write(text)
        return 0
    if args.factory_command == "scope":
        if not args.component:
            print("oto: scope takes the component (component.<id>) a run builds", file=sys.stderr)
            return 1
        try:
            run = _factory.scope(_session.live(project), args.component, cap=args.cap if args.cap is not None else 5, allow=args.allow or (),
                                 read_only=args.read_only or (), at=args.at)
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        out = args.out or os.path.join(".factory", "run.json")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(run, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("%s: the run snapshot of %s, write scope %s, read-only %s, cap %d" % (out, run["label"], ", ".join(run["write_scope"]), ", ".join(run["read_only"]), run["cap"]))
        print("  the factory plugin's hooks read it from the code repository's .factory/run.json; the spec it builds against is hash %s" % run["spec_hash"][:12])
        return 0
    if args.factory_command == "run":
        action = args.component
        try:
            if action == "start":
                if not args.plan or not os.path.isfile(args.plan):
                    print("oto: run start takes --plan <plan.json>, what `oto factory plan --json --out` wrote", file=sys.stderr)
                    return 1
                with open(args.plan, encoding="utf-8") as f:
                    plan_doc = json.load(f)
                done = _factory.run_start(plan_doc, args.at, run_id=args.id, runs_dir=args.runs or os.path.join(".factory", "runs"))
                print("run %s started at %s: %d build(s) in %d group(s), from %s" % (done["id"], done["dir"], done["builds"], done["groups"], args.plan))
                print("  the hooks append their decisions to .factory/events.jsonl; oto factory run sync --run %s --events <file> reads them in" % done["dir"])
                return 0
            if action == "record":
                done = _factory.run_record(args.run, args.component_id, args.iteration, args.verdict, gaps=args.gap or [], at=args.at, tests=args.tests)
                print("%s: iteration %s recorded as %s; the build is %s" % (args.component_id, args.iteration, args.verdict, done["state"]))
                return 0
            if action == "metrics":
                if not args.run and not args.runs:
                    print("oto: run metrics takes --run <run project> or --runs <directory of runs>", file=sys.stderr)
                    return 1
                m = _factory.run_metrics(run_dir=args.run, runs_dir=args.runs)
                if args.json:
                    print(json.dumps(m, indent=2, ensure_ascii=False))
                else:
                    sys.stdout.write(_factory.render_metrics(m))
                return 0
            if action == "sync":
                counts = _factory.run_sync(args.run, args.events)
                print("%s: %d event(s) read, %d new: %d iteration(s), %d passed, %d escalated%s" % (
                    args.events, counts["events"], counts["new"], counts["iterations"], counts["passed"], counts["escalated"],
                    ", %d skipped" % counts["skipped"] if counts["skipped"] else ""))
                return 0
            if action == "status":
                sys.stdout.write(_factory.run_status(args.run))
                return 0
            if action == "replay":
                if not args.component_id:
                    print("oto: run replay takes --component <id>", file=sys.stderr)
                    return 1
                sys.stdout.write(_factory.run_replay(args.run, args.component_id))
                return 0
            if action == "promote":
                if not args.into:
                    print("oto: run promote takes --into <main project>, where the result is proposed", file=sys.stderr)
                    return 1
                from ..project import Project
                done = _factory.run_promote(args.run, args.component_id, args.commit, args.at, Project.standard(args.into))
                rel = lambda p: os.path.relpath(p, args.into)  # noqa: E731
                print("run %s: %s passed after %d iteration(s), promoted with commit %s" % (done["run"], args.component_id, done["iterations"], args.commit))
                print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
                print("  proposal %s" % rel(done["proposal"]))
                print("  next, in %s: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\""
                      % (args.into, rel(done["proposal"])))
                return 0
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("oto: run takes start, record, sync, status, replay, metrics or promote", file=sys.stderr)
        return 1
    if args.factory_command == "criteria":
        if not args.context and not args.component_id:
            print("oto: criteria takes --context <bounded context> or --component <component>, and --out <dir>", file=sys.stderr)
            return 1
        import datetime
        at = args.at or datetime.date.today().isoformat()
        try:
            result = _factory.criteria(_session.live(project), context_id=args.context, component_id=args.component_id)
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        written = _factory.write_criteria(result, args.out or "criteria", at)
        kinds = {}
        for c in result["criteria"]:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        print("%s: %d criterion(s) for %s%s" % (args.out or "criteria", len(result["criteria"]), result["label"],
                                                 " (%s)" % ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items())) if kinds else ""))
        print("  %s, %s, %s" % (os.path.basename(written["markdown"]), os.path.basename(written["json"]), os.path.basename(written["tests"])))
        print("  review them before anything builds on them: every criterion names the nodes it came from, and the skeleton's tests are skipped until implemented")
        return 0
    if args.factory_command == "deviate":
        if not args.into:
            print("oto: deviate takes --run <dir> --component <id> --about <node> --observed \"...\" --proposes \"...\" --at <date> --into <main project>", file=sys.stderr)
            return 1
        from ..project import Project
        try:
            done = _factory.deviate(args.run, args.component_id, args.about, args.observed, args.proposes, args.at, Project.standard(args.into))
        except _factory.FactoryError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, args.into)  # noqa: E731
        nodes = {n["id"]: n for n in _session.live(Project.standard(args.into)).get("nodes") or [] if n.get("id")}
        print("deviation %s recorded: %s proposed as %s; the build of %s is failed until a person decides" % (done["id"], args.about, done["cp"], args.component_id))
        print("  affected siblings: %s" % (", ".join("%s (%s)" % (nodes.get(x, {}).get("label") or x, x) for x in done["siblings"]) or "none"))
        print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal %s" % rel(done["proposal"]))
        print("  next, in %s: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\"; "
              "then oto arch impact --decision once a decision settles it" % (args.into, rel(done["proposal"])))
        return 0
    print("oto: unknown factory command %r" % args.factory_command, file=sys.stderr)
    return 1


def register(sub):
    factory = sub.add_parser("factory", help="the factory's inputs, read from the graph: a component's spec, the build plan")
    factory.add_argument("factory_command", choices=["spec", "plan", "scope", "run", "criteria", "deviate"],
                         help="spec projects a component's spec as schema-checked, hashed JSON (--check a file); plan derives the build order from contract dependencies; "
                              "scope writes the run snapshot the factory plugin's hooks enforce; run keeps a run's own graph (start, record, sync, status, replay, metrics, promote); "
                              "criteria writes the acceptance criteria and a test skeleton from the graph; deviate records what was found impossible as specified")
    factory.add_argument("component", nargs="?", default=None, help="for spec and scope: the component, component.<id>; for run: start, record, sync, status, replay, metrics or promote")
    factory.add_argument("--check", default=None, metavar="FILE", help="for spec: verify a written spec's shape and hash")
    factory.add_argument("--out", default=None, help="write the spec or the plan here instead of printing it; for criteria, the directory (default criteria/)")
    factory.add_argument("--at", default=None, help="for spec: the date to record as generated (default: today)")
    factory.add_argument("--all", action="store_true", help="for plan: every CALM component, whatever its context's readiness")
    factory.add_argument("--context", default=None, help="for plan: the components one bounded context runs as")
    factory.add_argument("--json", action="store_true", help="for plan: the plan as JSON")
    factory.add_argument("--cap", type=int, default=None, help="for scope: the iteration cap of the run (default 5)")
    factory.add_argument("--allow", action="append", default=None, metavar="PATH", help="for scope: a path or glob added to the write scope; repeatable")
    factory.add_argument("--read-only", dest="read_only", action="append", default=None, metavar="PATH", help="for scope: a path added to the read-only paths beside contracts/; repeatable")
    factory.add_argument("--plan", default=None, help="for run start: the plan file `oto factory plan --json --out` wrote")
    factory.add_argument("--id", default=None, help="for run start: the run's id (default: r-<date>-<time>)")
    factory.add_argument("--runs", default=None, help="for run start and run metrics: the directory the run projects live in (default .factory/runs)")
    factory.add_argument("--run", default=None, help="for run record, sync, status, replay, metrics, promote: the run project's directory")
    factory.add_argument("--component", dest="component_id", default=None, help="for run record, replay, promote: the component, component.<id>")
    factory.add_argument("--iteration", default=None, help="for run record: the iteration's number, from 1")
    factory.add_argument("--verdict", default=None, help="for run record: pending, pass, fail or escalated")
    factory.add_argument("--gap", action="append", default=None, help="for run record: a gap the evaluator named; repeatable")
    factory.add_argument("--tests", default=None, help="for run record: what the tests said, pass, fail or unknown (default unknown)")
    factory.add_argument("--events", default=None, help="for run sync: the events file the loop hook wrote (.factory/events.jsonl)")
    factory.add_argument("--commit", default=None, help="for run promote: the sha the passed build is promoted with")
    factory.add_argument("--into", default=None, help="for run promote and deviate: the main project the result is proposed into")
    factory.add_argument("--about", default=None, help="for deviate: the node the deviation is about (a contract, an interface, a component)")
    factory.add_argument("--observed", default=None, help="for deviate: what was found impossible as specified, in a sentence")
    factory.add_argument("--proposes", default=None, help="for deviate: the change proposed, in a sentence")
    project_arguments(factory)
    factory.set_defaults(func=cmd_factory)
