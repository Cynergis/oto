# -*- coding: utf-8 -*-
"""`oto ddd`: the factory's domain graph. storm reads an event-storming board into a document and a
capture against the ddd vocabulary (roadmap I2)."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_ddd(args):
    from .. import ddd as _ddd
    project = _resolve(args)
    if args.ddd_command == "storm":
        if not args.from_:
            print("oto: storm takes --from <board.json>, the event-storming board to read", file=sys.stderr)
            return 1
        try:
            done = _ddd.storm(project, args.from_, args.at, name=args.name, context_id=args.context)
        except _ddd.DddError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %d sticky(ies) read into %d item(s) of the capture" % (done["doc"], done["stickies"], done["items"]))
        print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  capture  %s" % rel(done["capture"]))
        if done["gaps"]:
            print("  what the board does not say (the gates will ask):")
            for gap in done["gaps"]:
                print("    %s" % gap)
        print("  next: oto curate propose --from %s, then oto curate start, add --from proposals/%s.json, check, apply --by <you> --note \"...\"; "
              "then the analyst signs off: oto decide %s readiness=ready --by <name> --at <date>"
              % (rel(done["capture"]), done["doc"], "boundedcontext." + done["context"] if "." not in done["context"] else done["context"]))
        return 0
    print("oto: unknown ddd command %r" % args.ddd_command, file=sys.stderr)
    return 1


def register(sub):
    ddd = sub.add_parser("ddd", help="the factory's domain graph: an event-storming board in, through the capture form and the gates")
    ddd.add_argument("ddd_command", choices=["storm"], help="storm reads an event-storming board (--from) into a document and a capture")
    ddd.add_argument("--from", dest="from_", default=None, help="the board: JSON, stickies by kind and text")
    ddd.add_argument("--at", default=None, help="the date the board was read, YYYY-MM-DD; never defaulted")
    ddd.add_argument("--name", default=None, help="the document's slug (default: the board's context, else its session)")
    ddd.add_argument("--context", default=None, help="an existing BoundedContext the stickies belong to (default: the board's own, as a new context)")
    project_arguments(ddd)
    ddd.set_defaults(func=cmd_ddd)
