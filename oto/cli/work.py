# -*- coding: utf-8 -*-
"""`oto work`: the plan's states, set by appending a transition (M2, M3); the board (M5); a message
from a block to whom it waits on (M6)."""
import json
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
    if args.work_command == "board":
        board = _work.board(project)
        if board is None:
            print("oto: the vocabulary declares no WorkItem: the board needs the work ontology (oto init --ontology work)", file=sys.stderr)
            return 1
        print(json.dumps(board, indent=2, ensure_ascii=False) if args.json else _work.board_text(board, project.config().get("name")))
        return 0
    if args.work_command == "notify":
        by = args.by or _work.identity(project)
        try:
            done = _work.notify(project, args.item, by, args.at, body=args.body, to=args.to, due=args.due)
        except _work.WorkError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: message %s to %s%s, pending" % (done["label"], done["message"], done["to_label"], (", due " + args.due) if args.due else ""))
        print("  it carries the item, the block's date and reason, and what you added; citing assertion %s" % done["assertion"])
        print("Run `oto build`; the graph file is the record, commit it.")
        return 0
    return 1


def register(sub):
    work = sub.add_parser("work", help="the plan: set an item's state, see the board, tell whom a block waits on")
    work.add_argument("work_command", choices=["set", "board", "notify"],
                      help="set <item> --state open|blocked appends a transition; board shows open, blocked (by whom it waits on) "
                           "and deployed (by environment); notify <item> writes a message from its block to whom it waits on")
    work.add_argument("item", nargs="?", default=None, help="the work item: its id, label or alias")
    work.add_argument("--json", action="store_true", help="for board: the section as the snapshot carries it")
    work.add_argument("--to", default=None, help="for notify: whom to tell, when not whom the block waits on (a person, team or role)")
    work.add_argument("--due", default=None, help="for notify: when an answer is due, YYYY-MM-DD")
    work.add_argument("--body", default=None, help="for notify: what you add to the block's context")
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
