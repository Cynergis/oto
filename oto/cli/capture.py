# -*- coding: utf-8 -*-
"""`oto capture`: what someone said, written into the inbox as a dated source document."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_capture(args):
    from ..capture import write

    project = _resolve(args)
    statements = list(args.statement or [])
    if args.statements_file:
        with open(args.statements_file, encoding="utf-8") as f:
            statements += [line.strip().lstrip("-*0123456789. ").strip() for line in f if line.strip()]
    about = [x.strip() for x in (args.about or "").split(",") if x.strip()]
    try:
        path, warnings = write(project, args.title, statements, args.by, args.at, about=about,
                               context=args.context, recorded_by=args.recorded_by, force=args.force)
    except (ValueError, FileExistsError) as exc:
        message = "a note with that title and date exists: %s (pass --force to replace it)" % exc \
            if isinstance(exc, FileExistsError) else str(exc)
        print("oto: %s" % message, file=sys.stderr)
        return 1
    root = os.path.dirname(project.src)
    print("captured %s" % os.path.relpath(path, root))
    for warning in warnings:
        print("  note: %s" % warning)
    print("It is a source document in the inbox. Next:")
    if os.path.isdir(os.path.join(root, ".github", "workflows")):
        print("  git add %s && git commit -m 'capture: %s' && git push   # the pipeline ingests and opens the PR"
              % (os.path.relpath(path, root), args.title))
    else:
        print("  oto ingest --project %s     # then the curate skill, or build-knowledge-base" % root)
    return 0


def register(sub):
    capture = sub.add_parser("capture", help="write what someone said into the inbox as a dated source document")
    project_arguments(capture)
    capture.add_argument("--title", required=True, help="what the statements are about, as a short title")
    capture.add_argument("--by", required=True, help="who said it, and their role")
    capture.add_argument("--at", required=True,
                         help="the date the statements refer to, YYYY-MM-DD; never defaulted to today")
    capture.add_argument("--statement", action="append",
                         help="one statement, in the speaker's words (repeatable)")
    capture.add_argument("--statements-file", dest="statements_file", default=None,
                         help="a file with one statement per line, instead of or as well as --statement")
    capture.add_argument("--about", default=None, help="comma-separated entity ids the statements concern")
    capture.add_argument("--context", default=None, help="what prompted them, briefly")
    capture.add_argument("--recorded-by", dest="recorded_by", default=None,
                         help="who wrote this down (default: an agent, in conversation)")
    capture.add_argument("--force", action="store_true", help="replace a note with the same title and date")
    capture.set_defaults(func=cmd_capture)
