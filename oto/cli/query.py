# -*- coding: utf-8 -*-
"""`oto query` and `oto serve`: ask the knowledge base, or run the query server."""
import argparse
import os

from ._common import project_arguments, resolve as _resolve


def _target(args):
    """(database, config) for the directory named: a project, or a published store checkout."""
    from .. import publish as _publish

    root = os.path.abspath(args.project)
    if _publish.is_store(root):
        return _publish.store_paths(root)
    project = _resolve(args)
    return project.layout.database, project.config_path


def _preview_target(args, project):
    """Build the preview if needed and point the engine at it. Returns (database, config)."""
    from .. import preview as _preview
    if args.watch or args.preview:
        if not os.path.exists(_preview.database(project)) or args.watch:
            meta = _preview.build(project)
            print("oto serve: preview built: %d node(s), %d edge(s), %d pending change(s) in %.1fs"
                  % (meta["nodes"], meta["edges"], meta["differs"], meta["seconds"]), file=__import__("sys").stderr)
    return _preview.database(project), project.config_path


def _engine(target, backend=None):
    """Point the engine at this database and store backend, then import it.

    The path comes from the layout, never computed here: the two layouts put the database in
    different places, and a second copy of that logic is a second thing to get wrong. The backend
    flag wins over the project config's `serve.backend`; the engine reads both from the environment.
    """
    database, config = target
    os.environ["OTO_DB"] = database
    os.environ["OTO_PROJECT_CONFIG"] = config
    if backend:
        os.environ["OTO_STORE"] = backend
    from ..serve import engine
    return engine


def cmd_query(args):
    engine = _engine(_target(args), args.backend)
    if not args.query:
        print(engine.CLI_USAGE)
        return 2
    return engine.cli(args.query) or 0


def cmd_serve(args):
    """Serve the project over stdio, or over HTTP with --http, or an empty store with a plain
    message when there is no project here.

    A host may register this server for every directory it opens. Crashing in a directory that is
    not an OTO project would show the user a failed server for no reason; serving nothing, and
    saying why on every call, lets the same server start answering the moment the project exists
    and is built, because the engine re-checks the database file before each query.
    """
    import sys

    from ..project import ProjectError

    try:
        if getattr(args, "preview", False) or getattr(args, "watch", False):
            project = _resolve(args)
            if args.backend == "neo4j":
                print("oto serve: a preview is always the local SQLite build; --backend neo4j ignored for it", file=sys.stderr)
            engine = _engine(_preview_target(args, project), "sqlite")
        else:
            engine = _engine(_target(args), args.backend)
    except ProjectError as exc:
        root = os.path.abspath(args.project)
        os.environ["OTO_DB"] = os.path.join(root, "build", "oto.db")
        os.environ.pop("OTO_PROJECT_CONFIG", None)
        if args.backend:
            os.environ["OTO_STORE"] = args.backend
        print("oto serve: %s\n  serving nothing until `oto init` and `oto build` have run here; "
              "the server will pick the database up on the next call." % exc, file=sys.stderr)
        from ..serve import engine
    if args.http:
        from ..serve import http as _http
        from ..targets.site import resolve_app
        root = os.path.abspath(args.project)
        config_path = os.path.join(root, "project.config.json")
        identity = None
        if os.path.exists(config_path):
            import json
            with open(config_path, encoding="utf-8") as f:
                identity = json.load(f)
        project_root = root if os.path.exists(os.path.join(root, "ontology.config.json")) else None
        try:
            app_dir = resolve_app(args.view or "explorer", root)
            if app_dir:
                from ..apps import manifest as _apps
                problems = _apps.problems(app_dir)
                if problems:
                    raise ProjectError("app %r is not usable:\n  - %s" % (_apps.read(app_dir)["name"], "\n  - ".join(problems)))
        except ProjectError as exc:
            print("oto serve: %s" % exc, file=sys.stderr)
            return 1
        if args.preview or args.watch:
            from .. import preview as _preview
            project = _resolve(args)
            meta = _preview.read_meta(project) or {}
            engine.MODE.update({"regime": "watch" if args.watch else "preview", "preview_built_at": meta.get("built_at"),
                                "base_build_seq": meta.get("base_build_seq"), "differs": meta.get("differs", 0),
                                "counts": meta.get("counts"), "rebuilds": 0, "error": None})
            if args.watch:
                def on_built(m):
                    engine.MODE.update({"preview_built_at": m["built_at"], "differs": m["differs"], "counts": m["counts"],
                                        "rebuilds": engine.MODE.get("rebuilds", 0) + 1, "error": None})
                watcher = _preview.Watcher(project, on_built=on_built, log=engine.log).start()
                engine.MODE["watching"] = list(_preview.WATCHED)
        try:
            _http.serve(engine, args.http, app_dir=app_dir, project_root=project_root, identity=identity,
                        token=_http.token_from_env(), cors=args.cors or ())
        except _http.BindError as exc:
            print("oto serve: refused: %s" % exc, file=sys.stderr)
            return 1
        except OSError as exc:
            print("oto serve: cannot bind %s: %s" % (args.http, exc), file=sys.stderr)
            return 1
        return 0
    engine.main()
    return 0


def _backend_argument(parser):
    parser.add_argument("--backend", choices=("sqlite", "neo4j"), default=None,
                        help="serve from the local SQLite build or the configured Neo4j "
                             "(default: the project's `serve.backend`, else sqlite)")


def register(sub):
    query = sub.add_parser("query", help="ask the knowledge base a question")
    project_arguments(query)
    _backend_argument(query)
    query.add_argument("query", nargs=argparse.REMAINDER,
                       help="entity | neighbors | search | by-type | count | group | "
                            "stale | resolve | docs | overview | explain | policy | help")
    query.set_defaults(func=cmd_query)

    serve = sub.add_parser("serve", help="run the query server over stdio (JSON-RPC 2.0), or over HTTP")
    project_arguments(serve)
    _backend_argument(serve)
    serve.add_argument("--http", default=None, metavar="[HOST:]PORT",
                       help="serve over HTTP instead of stdio: POST /rpc, GET /api/graph and the tool routes. Binds to "
                            "127.0.0.1 unless a host is given; any other host requires OTO_SERVE_TOKEN in the "
                            "environment, and every call must then carry it as a bearer token")
    serve.add_argument("--cors", action="append", default=None, metavar="ORIGIN",
                       help="with --http: allow a browser app served from ORIGIN to call this server (repeatable; "
                            "`*` for any). Off by default")
    serve.add_argument("--preview", action="store_true",
                       help="serve the preview store (build/preview/: the live graph plus the candidate and every "
                            "proposal), built first if absent; the live store is untouched")
    serve.add_argument("--watch", action="store_true",
                       help="serve the preview and rebuild it whenever graph.json, the candidate, a proposal, the "
                            "vocabulary, the rules or the lexicon change (implies --preview)")
    serve.add_argument("--view", default=None,
                       help="with --http: the view to serve at /, by name or directory (default: the "
                            "built-in explorer; `reader` is the other built-in); its data files are generated from the graph")
    serve.set_defaults(func=cmd_serve)
