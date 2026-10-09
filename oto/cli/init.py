# -*- coding: utf-8 -*-
"""`oto init`: create a project, optionally from an ontology."""
import sys


def cmd_init(args):
    from ..scaffold import init

    try:
        init(args.project, slug=args.slug, name=args.name, namespace=args.namespace,
             prefix=args.prefix, force=args.force, ontology=args.ontology,
             repo=args.repo, engine=args.engine, pack=args.pack, empty=args.empty)
    except ValueError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    return 0


def register(sub):
    init = sub.add_parser("init", help="create a new project (data only, no engine code)")
    init.add_argument("--name", default=None,
                      help="the project's title, e.g. \"Acme Claims\"; the slug derives from it")
    init.add_argument("--slug", default=None,
                      help="short kebab id every generated name derives from (default: from --name)")
    init.add_argument("--project", default=".", help="target folder (default: current directory)")
    init.add_argument("--namespace", default=None,
                      help="base IRI of the RDF export: instances under id/, the project's own terms "
                           "under ont/ (default: from the slug)")
    init.add_argument("--prefix", default=None, help="RDF prefix (default: the slug)")
    init.add_argument("--force", action="store_true", help="overwrite existing config files")
    init.add_argument("--ontology", default=None,
                      help="start from an ontology, or several comma-separated (merged); a name from "
                           "`oto ontology list`, name@release, or a directory path")
    init.add_argument("--pack", default=None,
                      help="start from a pack: its ontology, with where it came from kept, and its views; a name "
                           "from `oto pack list` or a directory (inside Claude Code, the installed plugin's root)")
    init.add_argument("--empty", action="store_true",
                      help="install the vocabulary and leave the graph empty: a real product's graph holds what "
                           "its people said, not the ontology's example")
    init.add_argument("--repo", action="store_true",
                      help="lay the project out to live in a GitHub repository: workflows for ingest, "
                           "checks and deploy, a CLAUDE.md, an .mcp.json, and a corpus that is committed")
    init.add_argument("--engine", default=None,
                      help="git URL of the engine the repository installs (default: the OTO repository)")
    init.set_defaults(func=cmd_init)
