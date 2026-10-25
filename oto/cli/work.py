# -*- coding: utf-8 -*-
"""`oto work`: the plan's states, set by appending a transition (roadmap M2, M3)."""
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_work(args):
    from .. import work as _work

    project = _resolve(args)
    if args.work_command == "set":
        by = args.by or _work.identity(project)
        try:
            done = _work.set_state(project, args.item, args.state, by, args.at, reason=args.reason,
                                   waiting_on=args.waiting_on, environment=args.environment, note=args.note)
        except _work.WorkError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: %s -> %s%s (%s, by %s)" % (done["label"], done["from"], done["to"],
                                              (", waiting on %s" % done["waiting_on"]) if done["waiting_on"] else "",
                                              args.at, by))
        print("  transition %s appended, citing assertion %s%s" % (
            done["transition"], done["assertion"],
            ("; %s superseded" % ", ".join(done["superseded"])) if done["superseded"] else ""))
        print("Run `oto build` to derive the state; the graph file is the record, commit it.")
        return 0
    return 1


def register(sub):
    work = sub.add_parser("work", help="the plan: set an item's state by appending a transition")
    work.add_argument("work_command", choices=["set"], help="set <item> --state open|blocked: append a transition")
    work.add_argument("item", nargs="?", default=None, help="the work item: its id, label or alias")
    work.add_argument("--state", default=None, choices=["open", "blocked", "deployed"],
                      help="the state the item moves to; deployed is refused, an event sets it")
    work.add_argument("--reason", default=None, help="for blocked: why, in your words")
    work.add_argument("--waiting-on", dest="waiting_on", default=None,
                      help="for blocked: whom or what it waits on (a person, team, item, decision, question or risk: id or name)")
    work.add_argument("--environment", default=None, choices=["qa", "preprod", "prod"], help="for a deployment: where to")
    work.add_argument("--by", default=None, help="who records this (default: the git identity in the project)")
    work.add_argument("--at", default=None, help="the date it happened, YYYY-MM-DD; never defaulted")
    work.add_argument("--note", default=None, help="anything else worth recording with it")
    project_arguments(work)
    work.set_defaults(func=cmd_work)
