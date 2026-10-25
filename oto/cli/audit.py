# -*- coding: utf-8 -*-
"""`oto audit`: the hash-chained record of every write, verified and read."""
import sys

from .. import audit as _audit
from ._common import project_arguments, resolve as _resolve


def cmd_audit(args):
    project = _resolve(args)
    if args.audit_command == "verify":
        report = _audit.verify(project)
        if report["ok"]:
            print("audit log: %d record(s), chain intact" % report["records"])
            return 0
        print("audit log: %d record(s), chain BROKEN at record %s: %s" % (report["records"], report["broken"], report["why"]), file=sys.stderr)
        return 1
    if args.audit_command == "for":
        if not args.node:
            print("oto: audit for <node id>", file=sys.stderr)
            return 1
        records = _audit.for_node(project, args.node)
        if not records:
            print("no record touches %s" % args.node)
            return 0
        print("%d record(s) touch %s:" % (len(records), args.node))
        print(_audit.render(records, limit=args.show))
        return 0
    records = _audit.read(project)
    if not records:
        print("audit log: empty")
        return 0
    print("audit log: %d record(s), last %d:" % (len(records), min(len(records), args.show)))
    print(_audit.render(records, limit=args.show))
    return 0


def register(sub):
    audit = sub.add_parser("audit", help="the hash-chained record of every write: verify it, read it, ask who touched a node")
    audit.add_argument("audit_command", nargs="?", default="log", choices=["log", "verify", "for"],
                       help="log (the default) lists the latest records; verify walks the chain; for <node> lists what touched a node")
    audit.add_argument("node", nargs="?", default=None, help="for `for`: the node id")
    audit.add_argument("--show", type=int, default=50, help="how many records to list")
    project_arguments(audit)
    audit.set_defaults(func=cmd_audit)
