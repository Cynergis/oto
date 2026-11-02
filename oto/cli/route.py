# -*- coding: utf-8 -*-
"""`oto route`: the route a pull request takes into main, and its gate (docs/plans/graph-journeys.md).

    oto route show --base <ref> [--head <ref>] [--json]       the route the change asks for, and why
    oto route check --base <ref> [--head <ref>] [--author <id>]... [--approved] [--verified] [--json]
                                                                 the verdict: exit 0 when the route's rule holds
    oto route guardrails --base <ref> [--head <ref>] [--json]  the five guardrails on the change: additive, attributed, scope, clean, bounded

The author, the approval and the verification are what GitHub knows; the route workflow passes
them in. The engine reads the two trees with git and never calls GitHub."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_route(args):
    from .. import route as _route

    project = _resolve(args)
    root = project.data
    if not args.base:
        print("oto: route needs --base <ref>, the commit the pull request starts from (its base branch, or a sha)", file=sys.stderr)
        return 1
    try:
        if args.route_command == "check":
            result = _route.check(root, args.base, args.head or "HEAD", authors=args.author or (),
                                  approved=bool(args.approved), verified=bool(args.verified))
        elif args.route_command == "guardrails":
            result = _route.guardrails(root, args.base, args.head or "HEAD")
        else:
            result = _route.show(root, args.base, args.head or "HEAD")
    except _route.RouteError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    elif args.route_command == "guardrails":
        print(_route.render_guardrails(result))
    else:
        print(_route.render(result))
    if args.route_command in ("check", "guardrails"):
        return 0 if result.get("ok") else 1
    return 0


def register(sub):
    route = sub.add_parser("route", help="the route a pull request takes into main (session, guardrailed, reviewed), and its gate")
    route.add_argument("route_command", nargs="?", default="show", choices=["show", "check", "guardrails"],
                       help="show says the route the change between --base and --head asks for, and why; check is the gate's "
                            "verdict given what GitHub knows (--author, --approved, --verified): exit 0 when the route's rule holds; "
                            "guardrails runs the five guardrails of the guardrailed route on the change and names what each caught")
    route.add_argument("--base", default=None, help="the commit the pull request starts from: its base branch (origin/main) or a sha")
    route.add_argument("--head", default=None, help="the commit under review (default HEAD)")
    route.add_argument("--author", action="append", default=None,
                       help="for check: an identity GitHub gives the pull request, its author's login or a commit's email (repeatable)")
    route.add_argument("--approved", action="store_true", help="for check: a review approved the pull request")
    route.add_argument("--verified", action="store_true", help="for check: every commit of the pull request is verified (signed)")
    route.add_argument("--json", action="store_true", help="machine-readable output, for the workflow")
    project_arguments(route)
    route.set_defaults(func=cmd_route)
