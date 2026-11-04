# -*- coding: utf-8 -*-
"""`oto repo`: a project that lives in a GitHub repository (oto/repo.py writes its workflows with
`oto init --repo`); this command sets what the repository itself must have.

    oto repo access [--apply | --check | --owners] [--repo owner/name]
                                                    who holds which role (.github/oto-access.json, oto/access.py)
    oto repo commit --message <text> [--repo owner/name]
                                                    the staged change as a commit GitHub makes and signs

    oto repo rules [--apply] [--repo owner/name] [--code-owner <login|org/team>]
                                                    the branch rules on main (.github/oto-rules.json):
                                                    shown; with --apply, set through the GitHub CLI

The rules make the two checks required, `oto checks` and `oto route`, ask no approval at the branch
level (the route gate asks per route, docs/plans/graph-journeys.md) except a code owner's for what the
gate runs on (.github/CODEOWNERS: the workflows, the rules, the lock).
`--apply` sets up, in order: the code owners, which must be on main first; main's deploy key, kept in
the environment oto-main that only main deploys from, which the ingest and architecture workflows push
with; then the rules, which let that key and an administrator (by a pull request) past them, and
never GitHub Actions.
`oto sandbox up --repo` applies them when it creates the repository; this is the way for a repository
made otherwise, or after the rules file changed."""
import json
import os
import sys

from ._common import project_arguments


def _cmd_commit(root, args):
    from .. import repo as _repo
    from ..project import ProjectError
    if not args.message:
        print("oto: commit needs --message", file=sys.stderr)
        return 1
    repository = args.repo or _repo.origin_repository(root)
    if not repository:
        print("oto: no GitHub repository to commit to: pass --repo owner/name, or set `origin`", file=sys.stderr)
        return 1
    try:
        done = _repo.verified_commit(root, repository, args.message)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    print("GitHub made and signed the commit %s on %s; this branch now holds it" % (done["oid"][:12], done["branch"]))
    return 0


def _cmd_retire(root, args):
    from .. import directory as _directory, repo as _repo
    from ..project import ProjectError
    repository = args.repo or _repo.origin_repository(root)
    if not repository:
        print("oto: no GitHub repository: pass --repo owner/name, or set `origin`", file=sys.stderr)
        return 1
    try:
        done = _directory.retire(root, repository, args.confirm, neo4j=args.neo4j)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    print("archived %s, and took it off the directory's topic. Nothing was deleted, so unarchiving brings it back" % " and ".join(done["archived"]))
    if done["nodes_deleted"] is not None:
        print("deleted %d node(s) of this graph from Neo4j; every other graph there is untouched" % done["nodes_deleted"])
    else:
        print("its nodes are still in Neo4j: oto repo retire --neo4j, with the login in this terminal, deletes them")
    for line in done["warnings"]:
        print("  warning: %s" % line)
    print("  anyone holding its Neo4j login still has that login: change the password if it's shared with nothing else")
    return 0


def _cmd_access(root, args):
    from .. import access as _access, repo as _repo
    from ..project import ProjectError
    try:
        found = _access.load(root)
        if found is None:
            print("oto: no %s here: `oto init --repo` writes one" % _access.FILE, file=sys.stderr)
            return 1
        if args.owners:
            print("wrote %s from the stewards: commit it" % _repo.CODEOWNERS_FILE if _access.write_owners(root, found) else "%s already names the stewards" % _repo.CODEOWNERS_FILE)
            return 0
        if not args.apply and not args.check:
            print(json.dumps(found, indent=2, ensure_ascii=False))
            for problem in _access.problems(found):
                print("  problem: %s" % problem, file=sys.stderr)
            return 0
        repository = args.repo or _repo.origin_repository(root)
        if not repository:
            print("oto: no GitHub repository: pass --repo owner/name, or set `origin`", file=sys.stderr)
            return 1
        if args.check:
            drift = _access.drift(root, repository)
            if not drift:
                print("GitHub matches %s, on %s" % (_access.FILE, " and ".join(r for r, _store in _access._repositories(found, repository))))
                return 0
            print("GitHub differs from %s (%d):" % (_access.FILE, len(drift)))
            for line in drift:
                print("  %s" % line)
            return 1
        done = _access.apply(root, repository)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    for line in done["set"]:
        print("set %s" % line)
    for line in done["removed"]:
        print("removed %s" % line)
    for line in done["kept"]:
        print("kept %s" % line)
    if not done["set"] and not done["removed"]:
        print("nothing to change: GitHub already matches %s" % _access.FILE)
    if done["owners_differ"]:
        print("note: %s isn't the stewards the file names: oto repo access --owners writes it, then commit it" % _repo.CODEOWNERS_FILE)
    return 0


def cmd_repo(args):
    from .. import repo as _repo
    from ..project import ProjectError

    root = os.path.abspath(args.project)
    if args.repo_command == "access":
        return _cmd_access(root, args)
    if args.repo_command == "commit":
        return _cmd_commit(root, args)
    if args.repo_command == "retire":
        return _cmd_retire(root, args)
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
        result = _repo.apply_rules(root, repository, code_owner=args.code_owner)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    if result.get("workspace"):
        print("code owners: %s owns .github/, ontology/ and manifest.json (%s); a change to them needs that approval"
              % (result.get("code_owner"), _repo.CODEOWNERS_FILE.replace(os.sep, "/")))
        print("%s the branch rules %r on %s: pull requests required, the check pack check, one approval and a code owner's"
              % ("created" if result["created"] else "replaced", _repo.RULES_NAME, _repo._owner_name(repository)))
        print("release tags: only a maintainer or an administrator may make one (%s). The environment %s deploys from those tags alone: "
              "put the registry's token there, gh secret set OTO_REGISTRY_TOKEN --env %s" % (result.get("tag_rules"), result.get("environment"), result.get("environment")))
        return 0
    print("code owners: %s owns .github/ and oto.lock.json (%s); a change to them needs that approval"
          % (result.get("code_owner"), _repo.CODEOWNERS_FILE.replace(os.sep, "/")))
    print("main's deploy key: in the environment %s, which only main deploys from; the ingest and architecture workflows push with it"
          % result.get("environment"))
    print("%s the branch rules %r on %s (ruleset %s): pull requests required, the checks oto checks and oto route, "
          "no approvals at the branch level but a code owner's for what the gate runs on; "
          "past them only main's deploy key, and an administrator by a pull request"
          % ("created" if result["created"] else "replaced", _repo.RULES_NAME, _repo._owner_name(repository), result.get("id")))
    for warning in result.get("warnings") or []:
        print("  warning: %s" % warning)
    return 0


def register(sub):
    repo = sub.add_parser("repo", help="a project in a GitHub repository: the branch rules on main, shown or set (`oto init --repo` writes the workflows)")
    repo.add_argument("repo_command", nargs="?", default="rules", choices=["rules", "access", "commit", "retire"],
                      help="rules shows .github/oto-rules.json; with --apply, sets it on the repository through the GitHub CLI. access shows "
                           ".github/oto-access.json; --apply sets GitHub to match, --check says where it drifted, --owners writes CODEOWNERS from the stewards. "
                           "commit makes the staged change a commit through GitHub, verified with no key on this computer. "
                           "retire --confirm <owner/name> archives a graph and its store and takes it off the directory")
    repo.add_argument("--confirm", default=None, help="for retire: the repository's owner/name, typed out")
    repo.add_argument("--neo4j", action="store_true", help="for retire: also delete this graph's nodes from Neo4j, with the login in this environment")
    repo.add_argument("--apply", action="store_true", help="set the rules, or the access file, on GitHub")
    repo.add_argument("--check", action="store_true", help="for access: say where GitHub has drifted from the file, and exit 1 if it has")
    repo.add_argument("--owners", action="store_true", help="for access: write .github/CODEOWNERS from the stewards")
    repo.add_argument("--message", default=None, help="for commit: the commit's message")
    repo.add_argument("--repo", default=None, help="the repository, owner/name (default: where `origin` points)")
    repo.add_argument("--code-owner", default=None,
                      help="who owns what the gate runs on, a login or org/team (default: the one .github/CODEOWNERS names, else whoever gh is signed in as)")
    project_arguments(repo)
    repo.set_defaults(func=cmd_repo)
