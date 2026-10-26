# -*- coding: utf-8 -*-
"""`oto decide`: a named person moves a decision attribute of a node (readiness, a confirmation),
recorded as an assertion and applied under the gates."""
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_decide(args):
    from .. import decide as _decide
    project = _resolve(args)
    try:
        attribute, value = _decide.parse_assignment(args.assignment)
        done = _decide.move(project, args.node, attribute, value, args.by, args.at, note=args.note)
    except _decide.DecideError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    if done["already"]:
        print("%s (%s): %s is already %s; nothing recorded" % (done["label"], done["node"], done["attribute"], done["value"]))
        return 0
    print("%s (%s): %s is now %s, decided by %s on %s%s" % (done["label"], done["node"], done["attribute"], done["value"], args.by, args.at,
                                                            " (%s)" % args.note if args.note else ""))
    print("  recorded as assertion %s; the audit log has it. Next: oto build" % done.get("assertion"))
    return 0


def register(sub):
    decide = sub.add_parser("decide", help="a named person moves a decision attribute of a node: readiness, a confirmation")
    decide.add_argument("node", help="the node, by id")
    decide.add_argument("assignment", help="attribute=value: a decision attribute the vocabulary declares, and the value it moves to")
    decide.add_argument("--by", default=None, help="who decides; a decision has a name")
    decide.add_argument("--at", default=None, help="the date of the decision, YYYY-MM-DD; never defaulted")
    decide.add_argument("--note", default=None, help="anything worth recording with the decision")
    project_arguments(decide)
    decide.set_defaults(func=cmd_decide)
