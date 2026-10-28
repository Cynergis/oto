# -*- coding: utf-8 -*-
"""`oto work`: the plan's states, set by appending a transition (M2, M3); the board (M5); a message
from a block to whom it waits on (M6); the inbox a session opens with (N3); replies (N4); what a
merged pull request deployed."""
import json
import sys

from ...cli._common import project_arguments, resolve as _resolve


def cmd_work(args):
    from ... import tracing
    from ...project import ProjectError
    from .. import work as _work

    try:
        project = _resolve(args)
    except ProjectError:
        if args.work_command == "inbox" and args.hook:
            return 0                                   # a session opened outside a project: nothing to say
        raise
    with tracing.span("oto.work." + args.work_command, item=args.item, state=args.state, environment=args.environment):
        return _work_command(args, project, _work)


def _work_command(args, project, _work):
    if args.work_command == "set":
        by = args.by or _work.identity(project)
        try:
            done = _work.set_state(project, args.item, args.state, by, args.at, reason=args.reason,
                                   waiting_on=args.waiting_on, environment=args.environment, note=args.note)
        except _work.WorkError as exc:
            if not str(exc).startswith("refused by the gates"):
                _work.refused(project, "work set", by, args.item, exc)
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
            if not str(exc).startswith("refused by the gates"):
                _work.refused(project, "work notify", by, args.item, exc)
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: message %s to %s%s, pending" % (done["label"], done["message"], done["to_label"], (", due " + args.due) if args.due else ""))
        print("  it carries the item, the block's date and reason, and what you added; citing assertion %s" % done["assertion"])
        print("Run `oto build`; the graph file is the record, commit it.")
        return 0
    if args.work_command == "remind":
        try:
            done = _work.remind(project, args.at, by=args.by, dry_run=args.dry_run)
        except _work.WorkError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if not done["overdue"]:
            print("nothing overdue on %s: 0 reminder(s) sent" % args.at)
            return 0
        verb = "would send" if args.dry_run else "sent"
        print("%d overdue message(s) on %s; %d reminder(s) %s, %d already reminded today" % (
            len(done["overdue"]), args.at, len(done["sent"]), verb, done["already"]))
        for entry in done["sent"]:
            print("  %s -> %s (due %s)%s" % (entry["message"], entry["to_label"], entry["due"], (": reminder %s" % entry["reminder"]) if entry.get("reminder") else ""))
        if done["sent"] and not args.dry_run:
            print("Run `oto build`; the graph file is the record, commit it.")
        return 0
    if args.work_command == "inbox":
        try:
            found = _work.inbox(project, args.as_, principal=args.principal)
        except _work.WorkError as exc:
            if args.hook:
                return 0
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if found is None:
            if args.hook:
                return 0
            print("oto: the vocabulary declares no Message: the inbox needs the communication ontology (oto init --ontology communication)", file=sys.stderr)
            return 1
        if args.hook and not found["pending"]:
            return 0
        print(_work.inbox_text(found, project.config().get("name")))
        return 0
    if args.work_command == "reply":
        by = args.by or _work.identity(project)
        try:
            done = _work.reply(project, args.item, args.body, by, args.at, resolve_it=args.resolve, to=args.to)
        except _work.WorkError as exc:
            if not str(exc).startswith("refused by the gates"):
                _work.refused(project, "work reply", by, args.item, exc)
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: %s %s, by %s (%s)%s" % (done["message"], done["reply"], done["outcome"], by, args.at,
                                           (", to %s" % done["to"]) if done["to"] else ""))
        if done["transition"]:
            print("  %s: blocked -> open; transition %s appended" % (done["label"], done["transition"]))
        print("  citing assertion %s. Run `oto build`; the graph file is the record, commit it." % done["assertion"])
        return 0
    if args.work_command == "event" and args.item == "verdict":
        if not args.target_item:
            print("oto: event verdict takes --item <item> --run <id> --component <id> --verdict pass|fail|escalated [--gap ...] [--waiting-on <person>] --at YYYY-MM-DD", file=sys.stderr)
            return 1
        try:
            done = _work.event_verdict(project, args.target_item, args.run, args.component, args.verdict, args.at, by=args.by, gaps=args.gap or [], waiting_on=args.waiting_on)
        except _work.WorkError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if done.get("noted"):
            print("%s: run %s, %s passed; noted, nothing appended (deployed is set by a merge or a promotion)" % (done["label"], args.run, args.component))
            return 0
        print("%s: %s -> blocked (run %s, %s %s), waiting on %s" % (done["label"], done["from"], args.run, args.component, args.verdict, done.get("waiting_on") or args.waiting_on))
        print("  transition %s appended, citing assertion %s" % (done["transition"], done["assertion"]))
        print("Run `oto build`; the graph file is the record, commit it.")
        return 0
    if args.work_command == "event":
        if args.item != "merged-pr" or not (args.repo and args.number and args.target_item):
            print("oto: the events are `oto work event merged-pr --repo owner/name --number N --item <item> --environment qa|preprod|prod --at YYYY-MM-DD` "
                  "and `oto work event verdict --item <item> --run <id> --component <id> --verdict pass|fail|escalated --at YYYY-MM-DD`", file=sys.stderr)
            return 1
        try:
            done = _work.event_merged_pr(project, args.repo, args.number, args.target_item, args.environment, args.at, by=args.by)
        except _work.WorkError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if done.get("already"):
            print("%s: %s; nothing appended" % (done["label"], done.get("reason") or "%s already recorded as %s" % (done["event"], done["transition"])))
            return 0
        print("%s: %s -> deployed to %s (%s, %s)" % (done["label"], done["from"], args.environment, done["event"], args.at))
        print("  transition %s appended, citing assertion %s%s" % (done["transition"], done["assertion"],
                                                                  ("; %s superseded" % ", ".join(done["superseded"])) if done["superseded"] else ""))
        print("Run `oto build`; the graph file is the record, commit it.")
        return 0
    return 1


def register(sub):
    work = sub.add_parser("work", help="the plan: set an item's state, see the board, tell whom a block waits on")
    work.add_argument("work_command", choices=["set", "board", "notify", "inbox", "reply", "event", "remind"],
                      help="set <item> --state open|blocked appends a transition; board shows open, blocked (by whom it waits on) "
                           "and deployed (by environment); notify <item> writes a message from its block to whom it waits on; "
                           "inbox lists what is pending for you; reply <message> answers one (--resolve lifts the block); "
                           "event merged-pr records what a merged pull request deployed; remind --at <date> sends one reminder a day "
                           "for every pending message past its due date")
    work.add_argument("item", nargs="?", default=None, help="the work item (set, notify), the message (reply), or the event kind (event: merged-pr, verdict)")
    work.add_argument("--as", dest="as_", default=None, help="for inbox: whose inbox (default: the git identity, mapped to a Person)")
    work.add_argument("--hook", action="store_true", help="for inbox: print only when something waits, never fail (the SessionStart hook)")
    work.add_argument("--principal", default=None, help="for inbox: the identity the session runs under (default: $OTO_PRINCIPAL); the inbox is theirs and --as may only name them")
    work.add_argument("--dry-run", dest="dry_run", action="store_true", help="for remind: say what would be sent, write nothing")
    work.add_argument("--resolve", action="store_true", help="for reply: the reply settles what was asked, and lifts the block it was about")
    work.add_argument("--repo", default=None, help="for event merged-pr: owner/name")
    work.add_argument("--number", default=None, help="for event merged-pr: the pull request number")
    work.add_argument("--item", dest="target_item", default=None, help="for event: the work item the pull request delivered, or the factory built")
    work.add_argument("--run", default=None, help="for event verdict: the factory run's id")
    work.add_argument("--component", default=None, help="for event verdict: the component the factory built")
    work.add_argument("--verdict", default=None, help="for event verdict: pass, fail or escalated")
    work.add_argument("--gap", action="append", default=None, help="for event verdict: a gap the evaluator named; repeatable")
    work.add_argument("--json", action="store_true", help="for board: the section as the snapshot carries it")
    work.add_argument("--to", default=None, help="for notify and reply: whom to tell, when not whom the block waits on or who asked")
    work.add_argument("--due", default=None, help="for notify: when an answer is due, YYYY-MM-DD")
    work.add_argument("--body", default=None, help="for notify: what you add to the block's context; for reply: the answer")
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
