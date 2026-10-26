# -*- coding: utf-8 -*-
"""`oto factory`: the factory's inputs read from the graph. spec projects a component's spec,
schema-checked and hashed (roadmap I3); plan derives the build order from contract dependencies (I5)."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_factory(args):
    from .. import factory as _factory
    from ..curate import session as _session
    project = _resolve(args)
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
    print("oto: unknown factory command %r" % args.factory_command, file=sys.stderr)
    return 1


def register(sub):
    factory = sub.add_parser("factory", help="the factory's inputs, read from the graph: a component's spec, the build plan")
    factory.add_argument("factory_command", choices=["spec", "plan"],
                         help="spec projects a component's spec as schema-checked, hashed JSON (--check a file); plan derives the build order from contract dependencies")
    factory.add_argument("component", nargs="?", default=None, help="for spec: the component, component.<id>")
    factory.add_argument("--check", default=None, metavar="FILE", help="for spec: verify a written spec's shape and hash")
    factory.add_argument("--out", default=None, help="write the spec or the plan here instead of printing it")
    factory.add_argument("--at", default=None, help="for spec: the date to record as generated (default: today)")
    factory.add_argument("--all", action="store_true", help="for plan: every CALM component, whatever its context's readiness")
    factory.add_argument("--context", default=None, help="for plan: the components one bounded context runs as")
    factory.add_argument("--json", action="store_true", help="for plan: the plan as JSON")
    project_arguments(factory)
    factory.set_defaults(func=cmd_factory)
