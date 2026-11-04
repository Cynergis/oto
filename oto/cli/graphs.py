# -*- coding: utf-8 -*-
"""`oto graph`: this graph's descriptor, and the graphs it depends on (roadmap A1, A2). `oto graphs`: the graphs
a folder reads live from Neo4j (oto/connections.py)."""
import json
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_graph(args):
    from .. import assertion as _assertion, graphs as _graphs
    project = _resolve(args)
    if args.graph_command == "describe":
        if args.record:
            by = args.by or _assertion.identity(project)
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
        by = args.by or _assertion.identity(project)
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


def cmd_graphs(args):
    """`oto graphs`: the graphs this folder reads live from Neo4j, one connection each."""
    import os

    from .. import connections as _connections
    root = os.path.abspath(os.path.expanduser(args.project))
    if args.action == "add":
        if not args.name:
            print("oto: graphs add takes a name and the graph's address: oto graphs add <name> --uri neo4j+s://<id>.databases.neo4j.io", file=sys.stderr)
            return 1
        uri, database, slug, label, subject = args.uri, args.database, args.slug, args.label, args.subject
        if not uri and not args.server:
            from .. import directory as _directory
            listed = _directory.lookup(args.name)
            if listed is None:
                print("oto: no graph named %s in the registries this computer knows: pass --uri neo4j+s://<id>.databases.neo4j.io" % args.name, file=sys.stderr)
                return 1
            where = listed.get("neo4j") or {}
            if not where.get("uri"):
                print("oto: the directory lists %s (%s) with no Neo4j address, so it can't be read live: ask a steward, or pass --uri" % (args.name, listed.get("repository")), file=sys.stderr)
                return 1
            uri, database = where["uri"], database or where.get("database")
            slug, label, subject = slug or listed.get("slug"), label or listed.get("label"), subject or listed.get("subject")
        done = _connections.add(root, args.name, uri, database=database, slug=slug, label=label, subject=subject, server=args.server)
        if done["already"]:
            print("%s is already here; nothing changed" % done["name"])
        elif args.server:
            print("added the graph %s, read through its server at %s. `oto sandbox up` registers it with the sandbox tool as %s: no login enters the sandbox" % (done["name"], args.server, done["server"]))
        else:
            print("added the graph %s, read through the server %s (%s)" % (done["name"], done["server"], _connections.MCP_FILE))
        if args.server:
            return 0
        print("  its login goes in %s, in your terminal's environment and never in a file; `oto sandbox up` passes those into the sandbox it makes"
              % " and ".join(done["variables"]))
        return 0
    if args.action == "rm":
        if not args.name:
            print("oto: graphs rm takes the graph's name (oto graphs list)", file=sys.stderr)
            return 1
        done = _connections.remove(root, args.name)
        print("removed the graph %s and its server %s" % (done["name"], done["server"]))
        if done["kept"]:
            print("  kept what the connection did not write, in %s/%s: %s" % (_connections.FOLDER, done["name"], ", ".join(done["kept"])))
        print("  a sandbox made with its login still holds it: oto sandbox up --recreate makes one without it")
        return 0
    found = _connections.listed(root)
    if args.json:
        print(json.dumps({"graphs": found}, indent=2, ensure_ascii=False))
        return 0
    if not found:
        print("no graph here: oto graphs add <name> --uri neo4j+s://<id>.databases.neo4j.io")
        return 0
    print("%d graph(s) read live from Neo4j:" % len(found))
    for graph in found:
        print(connection_line(graph))
    return 0


def connection_line(graph):
    """One connection, for a person: never a login's value."""
    login = "login set" if graph["login"] else "NO LOGIN: set %s" % " and ".join(graph["variables"])
    return "  %-16s %s\n      %s%s, server %s; %s" % (graph["name"], graph["label"], graph["uri"], " (%s)" % graph["database"] if graph["database"] else "", graph["server"], login)


def register(sub):
    graphs = sub.add_parser("graphs", help="the graphs this folder reads live from Neo4j: add, list, rm")
    graphs.add_argument("action", nargs="?", default="list", choices=["add", "list", "rm"],
                        help="add <name> --uri ADDRESS: a connection, and a server of its own; list (the default): what is here, and whose "
                             "login is set; rm <name>: take one out")
    graphs.add_argument("name", nargs="?", help="for add and rm: the graph's name here, lowercase with hyphens; its server is <name>-kg")
    graphs.add_argument("--uri", default=None, help="for add: the graph's Neo4j address, e.g. neo4j+s://<id>.databases.neo4j.io (default: from the registry's directory, by the name)")
    graphs.add_argument("--server", default=None, help="for add: the graph's server on Cloud Run, its https /mcp URL, in place of a Neo4j address: no login enters the sandbox")
    graphs.add_argument("--database", default=None, help="for add: the database in that instance (on a new Aura instance, usually its id; default neo4j)")
    graphs.add_argument("--slug", default=None, help="for add: the slug the graph was loaded under, which selects it in the database (default: the name)")
    graphs.add_argument("--label", default=None, help="for add: what to call the graph (default: from the name)")
    graphs.add_argument("--subject", default=None, help="for add: what this graph holds, in a sentence: how Claude tells it from the others")
    graphs.add_argument("--json", action="store_true", help="for list: machine-readable")
    project_arguments(graphs)
    graphs.set_defaults(func=cmd_graphs)

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
