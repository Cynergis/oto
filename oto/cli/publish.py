# -*- coding: utf-8 -*-
"""`oto publish` and `oto sync`: the built store to a read-only query repository, and back to a reader."""
import os
import sys

from .. import publish as _publish
from ._common import project_arguments, resolve as _resolve


def cmd_publish(args):
    from .. import deploy as _deploy
    project = _resolve(args)
    if args.promote:
        if not args.to:
            print("oto: --promote needs --to <environment>", file=sys.stderr)
            return 2
        kind = args.approver
        by = args.by or (os.environ.get("GITHUB_ACTOR") if kind == "github" else None)
        entry = _deploy.promote(project, args.to, args.promote, by=by, kind=kind)
        print("promoted %s -> %s: %s (sha256 %s...)%s" % (entry["from"], entry["environment"], entry["source"],
                                                           entry["sha256"][:12],
                                                           (", approved by %s" % entry["approved_by"]) if entry["approved_by"] else ""))
        return 0
    manifest = _publish.publish(project, args.repo, source=args.source, branch=args.branch, engine=args.engine,
                                site=args.site, environment=args.to)
    where = ("environment %s of %s" % (args.to, manifest["repo"])) if args.to else args.repo
    if manifest["changed"]:
        print("published build_seq %d (%d bytes, sha256 %s...) to %s"
              % (manifest["build_seq"], manifest["bytes"], manifest["sha256"][:12], where))
    else:
        print("%s already holds this store (sha256 %s...); nothing pushed" % (where, manifest["sha256"][:12]))
    return 0


def cmd_sync(args):
    dest, manifest = _publish.sync(args.repo, dest=args.dest, branch=args.branch)
    print("synced %s -> %s" % (args.repo, dest))
    if manifest:
        print("  build_seq %s, published %s%s" % (manifest.get("build_seq"), manifest.get("published_at"),
                                                   (" from " + manifest["source"]) if manifest.get("source") else ""))
    print("  serve it:  oto serve --project %s   (or oto query --project %s ...)" % (dest, dest))
    return 0


def register(sub):
    publish = sub.add_parser("publish", help="push the built store to a read-only query repository")
    project_arguments(publish)
    publish.add_argument("--repo", default=None, help="the query repository: an https URL, ssh URL or local path "
                                                      "(not needed with --to: the deploy config names it)")
    publish.add_argument("--to", default=None, metavar="ENVIRONMENT",
                         help="an environment of oto.deploy.json: the first one takes the build; with --promote, the one "
                              "the previous environment's store is copied into")
    publish.add_argument("--promote", default=None, metavar="COMMIT",
                         help="promote: the commit the previous environment must hold; the same store moves, never a rebuild")
    publish.add_argument("--by", default=None, help="for --promote: who approved it (required where the environment names approvers)")
    publish.add_argument("--approver", default="person", choices=["person", "github"],
                         help="for --promote: how the approver was established; `github` records the run's actor "
                              "(GITHUB_ACTOR when --by is absent), behind the environment's required reviewers")
    publish.add_argument("--branch", default="main")
    publish.add_argument("--source", default=None, help="what produced it, e.g. org/knowledge@<sha>, recorded in the manifest")
    publish.add_argument("--engine", default=None, help="engine repository named in the store's README")
    publish.add_argument("--site", action="store_true",
                         help="also push build/site/ (from `oto build --target site`) as site/ beside the store")
    publish.set_defaults(func=cmd_publish)

    sync = sub.add_parser("sync", help="clone or update a published query store on this machine")
    sync.add_argument("--repo", required=True, help="the query repository")
    sync.add_argument("--dest", default=None, help="where to put it (default: the store's cache dir, ~/.<slug>-kg)")
    sync.add_argument("--branch", default="main")
    sync.set_defaults(func=cmd_sync)
