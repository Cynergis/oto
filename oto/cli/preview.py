# -*- coding: utf-8 -*-
"""`oto preview`: build the store the graph would be if everything pending went through."""
from ._common import project_arguments, resolve as _resolve


def cmd_preview(args):
    from .. import preview as _preview
    from ..curate import pending as _pending

    project = _resolve(args)
    if args.show:
        collected = _pending.collect(__import__("os").path.dirname(project.src))
        print(_pending.text(collected, limit=args.limit))
        return 0
    meta = _preview.build(project)
    print("preview: %d node(s), %d edge(s) -> %s  (%.1fs)" % (meta["nodes"], meta["edges"], _preview.database(project), meta["seconds"]))
    c = meta["counts"]
    print("  %d candidate change(s), %d proposed fact(s), %d refused; base build %s"
          % (c.get("candidate", 0), c.get("proposal", 0), c.get("refused", 0), meta["base_build_seq"]))
    print("  serve it:  oto serve --project %s --http 8765 --preview   (or --watch to rebuild on every change)"
          % __import__("os").path.dirname(project.src))
    return 0


def register(sub):
    preview = sub.add_parser("preview", help="build the preview store: the live graph plus the candidate and every proposal")
    project_arguments(preview)
    preview.add_argument("--show", action="store_true", help="only list what is pending, by station; build nothing")
    preview.add_argument("--limit", type=int, default=40, help="with --show: rows per station")
    preview.set_defaults(func=cmd_preview)
