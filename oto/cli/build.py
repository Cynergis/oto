# -*- coding: utf-8 -*-
"""`oto build`, `oto clean` and `oto verify`: compile every layer, delete it, prove the engine."""
import os

from ._common import project_arguments, resolve as _resolve


def cmd_build(args):
    from ..builder import build
    from ..validate.preflight import preflight

    project = _resolve(args)
    print("oto build: %s" % project)

    # Validate before writing anything. A build that fails halfway leaves a partly-written
    # build/ directory that looks complete.
    if not args.skip_preflight:
        summary = preflight(project)
        print("preflight ok: %(nodes)d nodes, %(edges)d edges, %(classes)d classes, "
              "%(properties)d properties" % summary)
        for warning in summary.get("warnings") or []:
            print("  note: %s" % warning)

    only = set(args.only.split(",")) if args.only else None
    project.options = {"targets": set(t.strip() for t in (args.target or []) if t.strip()), "verify": args.verify,
                       "view": args.view}
    build(project, only=only, transactional=not args.no_transaction)
    return 0


def cmd_clean(args):
    from ..builder import clean

    project = _resolve(args)
    targets = clean(project, dry_run=args.dry_run)
    if not targets:
        print("nothing to clean")
        return 0
    verb = "would remove" if args.dry_run else "removed"
    for path in targets:
        print("%s %s" % (verb, os.path.relpath(path, os.path.dirname(project.src))))
    if args.dry_run:
        print("\n(dry run; pass no --dry-run to delete)")
    else:
        print("\nrun `oto build` to regenerate")
    return 0


def cmd_verify(args):
    from ..validate.selftest import verify

    return 0 if verify() else 1


def register(sub):
    build = sub.add_parser("build", help="compile every layer")
    project_arguments(build)
    build.add_argument("--only", default=None,
                       help="comma-separated stage names to run (default: all)")
    build.add_argument("--skip-preflight", action="store_true",
                       help="skip validation (for debugging a partial build)")
    build.add_argument("--no-transaction", action="store_true",
                       help="write in place; a failure then leaves a partial build")
    build.add_argument("--target", action="append", default=None,
                       help="also load an optional target this time, e.g. neo4j (repeatable)")
    build.add_argument("--verify", action="store_true",
                       help="after loading an external target, read it back and compare with the build")
    build.add_argument("--view", default=None,
                       help="for the site target: the view, by name or directory, to copy beside "
                            "data.json (default: the built-in explorer)")
    build.set_defaults(func=cmd_build)

    clean = sub.add_parser("clean", help="delete everything the build generated")
    project_arguments(clean)
    clean.add_argument("--dry-run", action="store_true", help="list what would be removed")
    clean.set_defaults(func=cmd_clean)

    verify = sub.add_parser("verify", help="greenfield self-test: init, author, build, assert")
    verify.set_defaults(func=cmd_verify)
