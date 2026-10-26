# -*- coding: utf-8 -*-
"""`oto graph`: this graph's descriptor, and the graphs it depends on (roadmap A1, A2)."""
import json
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_graph(args):
    from .. import graphs as _graphs, work as _work
    project = _resolve(args)
    if args.graph_command == "describe":
        if args.record:
            by = args.by or _work.identity(project)
            if not (by or "").strip() or not args.at:
                print("oto: --record needs --by (or a git identity) and --at YYYY-MM-DD: the descriptor is a declared fact", file=sys.stderr)
                return 1
            try:
                written = _graphs.record_own(project, by, args.at)
            except _graphs.GraphError as exc:
                print("oto: %s" % exc, file=sys.stderr)
                return 1
            if written is None:
                print("%s already describes itself; nothing recorded" % _graphs.node_id(project.identity()["slug"]))
            else:
                print("%s recorded: this graph now describes itself. Run `oto build`; commit the graph file." % written)
            return 0
        print(json.dumps(_graphs.describe(project, reach=args.reach, subject=args.subject), indent=2, ensure_ascii=False))
        return 0
    if args.graph_command == "depend":
        if not args.on:
            print("oto: depend needs --on <descriptor.json>, what `oto graph describe` printed in the other project", file=sys.stderr)
            return 1
        try:
            with open(args.on, encoding="utf-8") as f:
                descriptor = json.load(f)
        except (OSError, ValueError) as exc:
            print("oto: %s: %s" % (args.on, exc), file=sys.stderr)
            return 1
        by = args.by or _work.identity(project)
        if not (by or "").strip() or not args.at:
            print("oto: depend needs --by (or a git identity) and --at YYYY-MM-DD: a dependency is a declared fact", file=sys.stderr)
            return 1
        try:
            done = _graphs.depend(project, descriptor, by, args.at)
        except _graphs.GraphError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if done.get("already"):
            print("this graph already depends on %s; nothing recorded" % done["node"])
            return 0
        print("%s depends on %s (%s), reached at %s" % (_graphs.node_id(project.identity()["slug"]), done["node"],
                                                        descriptor.get("subject"), descriptor.get("reach")))
        print("  recorded, citing assertion %s. Run `oto build`; commit the graph file." % done["assertion"])
        from ..curate import session as _session
        for found in _graphs.overlaps(_session.live(project).get("nodes")):
            if done["node"] in (found["a"], found["b"]):
                print("  warning: near-duplicate descriptors: %s" % found["message"])
        return 0
    found = _graphs.dependencies(project)
    if not found:
        print("%s depends on no other graph" % _graphs.node_id(project.identity()["slug"]))
        return 0
    print("%s depends on %d graph(s):" % (_graphs.node_id(project.identity()["slug"]), len(found)))
    for d in found:
        print("  %-28s %s\n      %s\n      reach %s · classes %s" % (d["id"], d["label"], d["subject"], d["reach"], ", ".join(d["classes"][:8])))
    return 0


def register(sub):
    graph = sub.add_parser("graph", help="this graph's descriptor, and the graphs it depends on")
    graph.add_argument("graph_command", nargs="?", default="dependencies", choices=["describe", "depend", "dependencies"],
                       help="describe prints this graph's descriptor (--record writes it into a project made before descriptors); "
                            "depend --on <descriptor.json> declares a dependency; dependencies (the default) lists them")
    graph.add_argument("--reach", default=None, help="for describe: how the graph is reached from outside (default: its MCP server name)")
    graph.add_argument("--subject", default=None, help="for describe: what this graph holds, in place of the inferred subject; "
                                                        "say what only this graph holds when another descriptor says nearly the same")
    graph.add_argument("--record", action="store_true", help="for describe: write this graph's own descriptor into the graph, through the gates")
    graph.add_argument("--on", default=None, help="for depend: the other graph's descriptor file")
    graph.add_argument("--by", default=None, help="who declares it (default: the git identity in the project)")
    graph.add_argument("--at", default=None, help="the date, YYYY-MM-DD")
    project_arguments(graph)
    graph.set_defaults(func=cmd_graph)
