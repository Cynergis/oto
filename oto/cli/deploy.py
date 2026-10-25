# -*- coding: utf-8 -*-
"""`oto deploy`: the deploy config, checked before anything publishes; what is in each environment."""
import sys

from .. import deploy as _deploy
from ._common import project_arguments, resolve as _resolve


def cmd_deploy(args):
    project = _resolve(args)
    if args.deploy_command == "init":
        if _deploy.exists(project) and not args.force:
            print("oto: %s exists; pass --force to replace it" % _deploy.NAME, file=sys.stderr)
            return 1
        if not args.repo or not args.to:
            print("oto: init needs --repo <owner/name> (the repository the graph is compiled from) and --to <query "
                  "repository> (where the store is published)", file=sys.stderr)
            return 2
        config = _deploy.starter(args.repo, args.to, project.identity()["slug"], connector=args.connector)
        _deploy.write(project, config)
        print("wrote %s: %s, connector %s, environments %s" % (_deploy.NAME, args.repo, args.connector,
                                                                " -> ".join(_deploy.chain(config))))
        print("  edit the approvers, then: oto deploy check")
        return 0

    if not _deploy.exists(project):
        print("no %s: this project has no deploy config. `oto deploy init --repo <owner/name> --to <query repository>` "
              "writes one; without it `oto publish --repo` works as before, one store, no environments." % _deploy.NAME)
        return 0
    config = _deploy.load(project)
    problems = _deploy.problems(config)

    if args.deploy_command == "check":
        if problems:
            print("%s does not validate (%d problem(s)):" % (_deploy.NAME, len(problems)))
            for problem in problems:
                print("  %s" % problem)
            return 1
        print("%s validates: %s, graph %s, connector %s" % (_deploy.NAME, config["repo"], config["graph"], config["connector"]))
        print("  publish to  %s%s" % (config["publish"]["to"], " (through a pull request)" if config["publish"].get("require_pr") else ""))
        print("  environments %s" % " -> ".join(_deploy.chain(config)))
        for name in _deploy.chain(config):
            who = _deploy.approvers(config, name)
            print("    %-8s %s" % (name, ("approved by " + ", ".join(who)) if who else "no approver: the build lands here"))
        print("  promotion   %s: the store one environment holds is copied to the next, never rebuilt" % config.get("promotion", _deploy.PROMOTION))
        return 0

    # status
    if problems:
        print("oto: %s does not validate; run `oto deploy check`" % _deploy.NAME, file=sys.stderr)
        return 1
    held = _deploy.status(project)
    print("what each environment of %s holds:" % config["publish"]["to"])
    for name in _deploy.chain(config):
        entry = held.get(name)
        if not entry:
            print("  %-8s nothing yet" % name)
            continue
        who = ("approved by %s (%s)" % (entry["approved_by"], entry.get("approver_kind") or "person")) if entry.get("approved_by") \
            else "published, no approver needed"
        print("  %-8s build %s from %s · %s · %s%s" % (name, entry.get("build_seq"), entry.get("source") or "?", entry.get("at"), who,
                                                     (" · from %s" % entry["from"]) if entry.get("from") else ""))
    return 0


def register(sub):
    deploy = sub.add_parser("deploy", help="the deploy config (oto.deploy.json): check it, write a starter, see what each environment holds")
    deploy.add_argument("deploy_command", nargs="?", default="check", choices=["check", "init", "status"],
                        help="check validates the config (the default); init writes a starter with --repo and --to; "
                             "status reads the query repository and says what each environment holds and who approved it")
    project_arguments(deploy)
    deploy.add_argument("--repo", default=None, help="for init: the repository the graph is compiled from, owner/name")
    deploy.add_argument("--to", default=None, help="for init: the query repository the store is published to")
    deploy.add_argument("--connector", default="sqlite", choices=list(_deploy.CONNECTORS), help="for init: the store (default sqlite)")
    deploy.add_argument("--force", action="store_true", help="for init: replace an existing config")
    deploy.set_defaults(func=cmd_deploy)
