# -*- coding: utf-8 -*-
"""`oto pack`: the full extension a person installs into Claude Code.

    oto pack new <name> --ontology <name|name@r|dir> [--domain d] [--summary s] [--view <dir>]...
    oto pack check [<dir>]            the self-check of the pack in the current directory, or one named
    oto pack refresh [<name|dir>]     re-embed the ontology at its current release; regenerate the plugin files
    oto pack list                     every pack on this machine, and what a registry lists that is not here
    oto pack show <name|dir>          the manifest, the embedded ontology, the skills, the views, the checks
    oto pack add <name|name@r|url>    fetch one from a registry
    oto pack update [<name>]          re-fetch newer releases
    oto pack publish --to <registry>  release it

A verb with a name acts on the catalog; `check` and `refresh` with no name act on the pack in
the current directory.
"""
import os
import sys


def _here_or(which):
    """The pack directory a verb acts on: the argument, or the current directory."""
    from ..model import packs
    target = which[0] if which else "."
    directory = packs.dir_for(target if os.sep in target or target.startswith(".") else target) \
        or packs.dir_for(os.path.abspath(target))
    return directory


def cmd_pack(args):
    from ..model import packs

    verb = args.pack_command
    which = list(args.which or [])
    if verb == "new":
        if not which:
            print("oto: new needs a name (and --ontology <name|dir>, --from-project <dir>, or --extends <name,...> for a workspace to fill)",
                  file=sys.stderr)
            return 1
        starter = not args.ontology and not args.from_project
        if starter and not args.to:
            print("oto: a workspace with a starter vocabulary needs --to <dir>, a directory of its own (a git repository); "
                  "under the packs directory a pack is an installed one: oto pack new <name> --ontology <name|dir>", file=sys.stderr)
            return 1
        try:
            directory, problems = packs.new(which[0], args.ontology, domain=args.domain, summary=args.summary,
                                            view_dirs=args.view or (), to=args.to, force=args.force,
                                            maintainer=args.maintainer, from_project=args.from_project,
                                            extends=[e.strip() for e in (args.extends or "").split(",") if e.strip()])
        except FileExistsError as exc:
            print("oto: %s already exists; pass --force to replace it" % exc, file=sys.stderr)
            return 1
        except (ValueError, OSError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        manifest = packs.read(directory)
        onto = manifest["ontology"]
        is_workspace = os.path.exists(os.path.join(directory, packs.TRIAL_DIR))
        print("wrote the %s %r to %s" % ("workspace" if is_workspace else "pack", which[0], directory))
        if args.from_project:
            print("  the vocabulary from the project %s, as the ontology %s@%s" % (os.path.abspath(args.from_project), onto["name"], onto["release"]))
        elif starter:
            print("  a starter vocabulary %s@%s to fill, on %s" % (onto["name"], onto["release"],
                                                                   ", ".join(packs.embedded_manifest(directory).get("extends") or []) or "nothing"))
        else:
            print("  embeds the ontology %s@%s (%s)" % (onto["name"], onto["release"], onto.get("registry") or onto.get("source")))
        print("  wrote: %s, skills/%s/SKILL.md, README.md%s" % (os.path.join(packs.PLUGIN_DIR, "plugin.json"), packs.START_SKILL,
                                                            ", trial/ (a project to try it in), .github/workflows/ (check, publish)" if is_workspace else ""))
        for note in packs.notes(directory):
            print("  note: %s" % note)
        if problems and starter:
            print("  not yet usable (%d problem(s)): the interview fills ontology/%s/ (the ontology-interview skill), then: "
                  "oto pack check %s --strict, oto pack try %s" % (len(problems), onto["name"], directory, directory))
            return 0
        if problems:
            print("  %d problem(s) the check found:" % len(problems))
            for problem in problems[:10]:
                print("    %s" % problem)
            return 1
        print("  check clean. Add skills under skills/ and views under views/, then: oto pack check %s%s"
              % (directory, (" and oto pack try %s" % directory) if is_workspace else ""))
        return 0

    if verb == "try":
        directory = _here_or(which)
        if directory is None:
            print("oto: %s is not a pack" % (which[0] if which else os.getcwd()), file=sys.stderr)
            return 1
        try:
            code, said = packs.try_(directory)
        except (ValueError, OSError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("trial %s: vocabulary written from the pack, built; its questions:" % os.path.join(directory, packs.TRIAL_DIR))
        for line in said.strip().splitlines():
            print("  " + line)
        return code

    if verb == "check":
        directory = _here_or(which)
        if directory is None:
            print("oto: %s is not a pack (no manifest.json with an ontology/ beside it)" % (which[0] if which else os.getcwd()),
                  file=sys.stderr)
            return 1
        manifest = packs.read(directory)
        problems = packs.check(directory, strict=bool(getattr(args, "strict", False)))
        onto = manifest.get("ontology") or {}
        print("pack %s @%s: ontology %s@%s, %d skill(s), %d view(s)%s"
              % (manifest["name"], manifest["release"], onto.get("name"), onto.get("release"),
                 len(packs.skills(directory)), len(packs.views(directory)), "; the rationale held to, too" if getattr(args, "strict", False) else ""))
        for note in packs.notes(directory):
            print("  note: %s" % note)
        if problems:
            print("  %d problem(s):" % len(problems))
            for problem in problems:
                print("    - %s" % problem)
            return 1
        print("  check clean")
        return 0

    if verb == "refresh":
        directory = _here_or(which)
        if directory is None:
            print("oto: %s is not a pack" % (which[0] if which else os.getcwd()), file=sys.stderr)
            return 1
        from ..project import ProjectError
        try:
            old, new = packs.refresh(directory)
        except (ValueError, ProjectError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        onto = packs.read(directory)["ontology"]
        print("%s: ontology %s at release %s (was %s); plugin manifest and starter skill regenerated"
              % (packs.read(directory)["name"], onto["name"], new, old))
        problems = packs.check(directory)
        if problems:
            print("  %d problem(s) remain: oto pack check %s" % (len(problems), directory))
            return 1
        return 0

    from . import pack_catalog as _catalog
    return _catalog.run(args)


def register(sub):
    pack = sub.add_parser("pack", help="the full extension a person installs into Claude Code: an ontology, its skills and its views")
    pack.add_argument("pack_command", nargs="?", default="list",
                      choices=["new", "check", "try", "refresh", "list", "show", "add", "update", "publish"],
                      help="new <name> --ontology <name> scaffolds one; check [<dir>] validates it; refresh [<dir>] "
                           "re-embeds the ontology at its current release; list (default) shows every pack; "
                           "show <name> prints one; add <name|name@release|url> fetches one; update re-fetches "
                           "newer releases; publish --to <registry> releases one")
    pack.add_argument("which", nargs="*", default=None,
                      help="new: the pack's name; check and refresh: a directory (default .); show: a name or "
                           "directory; add: a name, name@release or git URL; update: a name")
    pack.add_argument("--ontology", default=None, help="for new: the ontology to embed, a name on this machine, name@release, or a directory")
    pack.add_argument("--extends", default=None, help="for new without --ontology: the ontologies the starter vocabulary rests on, comma-separated (default oto-core)")
    pack.add_argument("--from-project", dest="from_project", default=None, help="for new: open a workspace from a project that grew its own vocabulary")
    pack.add_argument("--strict", action="store_true", help="for check: hold the rationale to it too, a reason and a confirmation per term")
    pack.add_argument("--patterns", action="store_true",
                      help="for list: only the pattern packs (a pack whose manifest says what it is a design pattern of)")
    pack.add_argument("--playbooks", action="store_true",
                      help="for list: only the playbook packs (a pack whose manifest names the journey one of its skills leads)")
    pack.add_argument("--bindings", action="store_true",
                      help="for list: only the binding packs (a pack whose manifest says what it binds to a platform)")
    pack.add_argument("--domain", default=None, help="for new: the category the pack belongs to, one lowercase slug (default: the ontology's)")
    pack.add_argument("--summary", default=None, help="for new and publish: one line saying what the pack is for")
    pack.add_argument("--view", action="append", default=None, help="for new: a view directory to ship (repeatable)")
    pack.add_argument("--maintainer", default=None, help="for new: who maintains it, named in the plugin manifest")
    pack.add_argument("--to", default=None, help="for new: the directory to write under (default: ~/.oto/packs); for publish: the registry's git URL")
    pack.add_argument("--from", dest="from_name", default=None, help="for publish: the pack on this machine to publish (default: the current directory)")
    pack.add_argument("--note", default=None, help="for publish: the changelog entry for this release")
    pack.add_argument("--ref", default=None, help="for add <url> and publish: a branch or tag")
    pack.add_argument("--path", default=None, help="for add <url>: the pack's directory inside the repository")
    pack.add_argument("--registry-name", dest="registry_name", default=None, help="for publish into an empty repository: the registry's name")
    pack.add_argument("--engine", default=None, help="for publish: the engine repository the registry's check workflow installs")
    pack.add_argument("--force", action="store_true", help="for new and add: replace an existing pack of that name")
    pack.set_defaults(func=cmd_pack)
