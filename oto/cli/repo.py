# -*- coding: utf-8 -*-
"""`oto repo`: a project that lives in a GitHub repository (oto/repo.py writes its workflows with
`oto init --repo`); this command sets what the repository itself must have.

    oto repo rules [--apply] [--repo owner/name]    the branch rules on main (.github/oto-rules.json):
                                                    shown; with --apply, set through the GitHub CLI

The rules make the two checks required, `oto checks` and `oto route`, ask no approval at the branch
level (the route gate asks per route, docs/plans/graph-journeys.md), and turn the merge queue on.
`oto sandbox up --repo` applies them when it creates the repository; this is the way for a repository
made otherwise, or after the rules file changed."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_repo(args):
    from .. import repo as _repo
    from ..project import ProjectError

    project = _resolve(args)
    root = project.data
    if args.repo_command != "rules":
        print("oto: repo knows one verb, rules", file=sys.stderr)
        return 1
    path = os.path.join(root, _repo.RULES_FILE)
    if not os.path.exists(path):
        print("oto: %s is not there: `oto init --repo` writes it (a project laid out before it existed: oto init --repo --force keeps your edits and adds what is missing)"
              % os.path.relpath(path, root), file=sys.stderr)
        return 1
    if not args.apply:
        with open(path, encoding="utf-8") as f:
            rules = json.load(f)
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        repository = args.repo or _repo.origin_repository(root) or "<owner/name>"
        print("\nnot applied. To set them on GitHub: oto repo rules --apply%s (the GitHub CLI, signed in as someone who administers the repository)"
              % ("" if args.repo or _repo.origin_repository(root) else " --repo owner/name"), file=sys.stderr)
        print("repository: %s" % repository, file=sys.stderr)
        return 0
    repository = args.repo or _repo.origin_repository(root)
    if not repository:
        print("oto: no GitHub repository to set the rules on: pass --repo owner/name, or set `origin`", file=sys.stderr)
        return 1
    try:
        result = _repo.apply_rules(root, repository)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    print("%s the branch rules %r on %s (ruleset %s): pull requests required, the checks oto checks and oto route, "
          "no approvals at the branch level, the merge queue on"
          % ("created" if result["created"] else "replaced", _repo.RULES_NAME, _repo._owner_name(repository), result.get("id")))
    return 0


def register(sub):
    repo = sub.add_parser("repo", help="a project in a GitHub repository: the branch rules on main, shown or set (`oto init --repo` writes the workflows)")
    repo.add_argument("repo_command", nargs="?", default="rules", choices=["rules"],
                      help="rules shows .github/oto-rules.json; with --apply, sets it on the repository through the GitHub CLI")
    repo.add_argument("--apply", action="store_true", help="set the rules on GitHub (a ruleset named after them is replaced)")
    repo.add_argument("--repo", default=None, help="the repository, owner/name (default: where `origin` points)")
    project_arguments(repo)
    repo.set_defaults(func=cmd_repo)
