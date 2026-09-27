# -*- coding: utf-8 -*-
"""`oto feedback`: record what a reader said about an answer, and make it a test."""
import os
import sys

from ._common import project_arguments, resolve as _resolve, today as _today


def cmd_feedback(args):
    """Record what a reader said about an answer, and turn it into a permanent test."""
    from ..bench import feedback as _feedback

    project = _resolve(args)

    if args.feedback_command == "record":
        missing = [name for name in ("question", "verdict", "by") if not getattr(args, name)]
        if missing:
            print("oto: record needs --%s" % ", --".join(missing), file=sys.stderr)
            return 1
        try:
            entry = _feedback.record(
                project, args.question, args.verdict, args.by, args.at or _today(),
                given=args.given, expected=args.expected,
                sources=args.source or None, note=args.note)
        except ValueError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("recorded %s: %s" % (entry["id"], entry["verdict"]))
        if _feedback._blocker(entry) and entry["verdict"] in _feedback.PROMOTABLE:
            print("This cannot become a test yet: it %s" % _feedback._blocker(entry))
            print("Add --expected when you know the right answer.")
        return 0

    ready, blocked = _feedback.pending(project)
    entries = _feedback.read(project)

    if args.feedback_command == "list":
        if not entries:
            print("no feedback recorded yet")
            return 0
        counts = {}
        for entry in entries:
            counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
        print("%d entries: %s" % (len(entries),
              ", ".join("%s %s" % (n, v) for v, n in sorted(counts.items()))))
        print()
        done = _feedback.promoted_ids(project)
        for entry in entries:
            mark = "promoted" if entry["id"] in done else entry["verdict"]
            print("  %s  [%-10s] %s" % (entry["id"], mark, entry["question"]))
            if entry.get("note"):
                print("              %s" % entry["note"])
        print()
        print("%d ready to promote, %d blocked" % (len(ready), len(blocked)))
        for entry, reason in blocked:
            print("  %s blocked: %s" % (entry["id"], reason))
        return 0

    if args.feedback_command == "promote":
        path = args.gold or os.path.join(project.data, "gold", "questions.jsonl")
        if not os.path.exists(path):
            print("oto: no gold set at %s. Run `oto bench start` first." % path, file=sys.stderr)
            return 1
        if not ready:
            print("nothing to promote: %d blocked, %d already promoted"
                  % (len(blocked), len(_feedback.promoted_ids(project))))
            for entry, reason in blocked:
                print("  %s: %s" % (entry["id"], reason))
            return 0
        wanted = args.id or None
        try:
            added, skipped, before, after, inherited = _feedback.promote(
                project, path, ids=wanted, kind=args.type)
        except ValueError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if not added:
            print("nothing promoted")
            for entry, reason in skipped:
                print("  %s: %s" % (entry["id"], reason))
            return 0
        print("promoted %d question(s) into %s" % (len(added), os.path.basename(path)))
        for entry, question in added:
            print("  %s -> %s" % (entry["id"], question["id"]))
        if before.get("authored_by_kind") != after.get("authored_by_kind"):
            print()
            print("Provenance changed: %s -> %s. Promoted questions are unaudited, so the set is now "
                  "weaker than it was. Every report will say so."
                  % (before.get("authored_by_kind"), after.get("authored_by_kind")))
        if before.get("audited_fraction") != after.get("audited_fraction"):
            print("Audited fraction: %s -> %s" % (before.get("audited_fraction"),
                                                  after.get("audited_fraction")))
        if inherited:
            print()
            print("The set already had %d problem(s). Promotion did not cause them, and did not fix "
                  "them. `oto bench` will still refuse to run until they are resolved:"
                  % len(inherited))
            for problem in inherited[:10]:
                print("  %s" % problem)
            if len(inherited) > 10:
                print("  ... and %d more" % (len(inherited) - 10))
        return 0

    print("oto: unknown feedback command %r" % args.feedback_command, file=sys.stderr)
    return 1


def register(sub):
    from ..bench.feedback import VERDICTS as _VERDICTS  # single definition, no drift

    feedback = sub.add_parser("feedback",
                              help="record what a reader said about an answer, and make it a test")
    feedback.add_argument("feedback_command", nargs="?", default="list",
                          choices=["record", "list", "promote"],
                          help="record adds one entry; list shows them; promote turns them into "
                               "gold questions")
    project_arguments(feedback)
    feedback.add_argument("--question", help="the question that was asked")
    feedback.add_argument("--verdict", choices=list(_VERDICTS),
                          help="wrong, incomplete, unsupported or right")
    feedback.add_argument("--by", help="who is saying this (required: feedback needs an author)")
    feedback.add_argument("--at", help="date, YYYY-MM-DD (default: today)")
    feedback.add_argument("--given", help="the answer the system gave")
    feedback.add_argument("--expected", help="the right answer; without it this cannot become a test")
    feedback.add_argument("--source", action="append",
                          help="a source the answer should have cited (repeatable)")
    feedback.add_argument("--note", help="anything else worth keeping")
    feedback.add_argument("--gold", default=None,
                          help="gold set to promote into (default: <project>/gold/questions.jsonl)")
    feedback.add_argument("--id", action="append", help="promote only these feedback ids (repeatable)")
    feedback.add_argument("--type", default="factual", help="gold question type for promoted entries")
    feedback.set_defaults(func=cmd_feedback)
