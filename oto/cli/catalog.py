# -*- coding: utf-8 -*-
"""The catalog half of `oto ontology`: the ontologies on this machine and in the registries.

    oto ontology list                         every ontology on this machine, and what a registry lists
    oto ontology show <name>                  one in full
    oto ontology export --name <name>         write one from this project
    oto ontology add <name|name@release|url>  fetch one
    oto ontology update [<name>]              re-fetch newer releases
    oto ontology diff                         what upstream changed since this project started from it
    oto ontology publish --to <registry url>  push this project's vocabulary, or --from <name>

A verb with no name acts on the project's own ontology (`ontology.py`); a verb with a name acts
on the catalog. This module holds the second family; `ontology.py` dispatches to `run`.
"""
import os
import sys

VERBS = ("list", "show", "export", "add", "update", "diff", "publish")


def run(args):
    """Run a catalog verb. Returns an exit code."""
    from ..model import ontologies

    verb = args.ontology_command
    if verb in ("add", "update", "publish", "diff"):
        return _remote(args)
    if verb == "export":
        from ._common import resolve as _resolve

        if not args.name:
            print("oto: export needs --name <ontology-name>", file=sys.stderr)
            return 1
        project = _resolve(args)
        try:
            path, problems = ontologies.export(project, args.name, to=args.to, from_graph=args.from_graph,
                                               summary=args.summary, force=args.force, invented=args.invented)
        except FileExistsError as exc:
            print("oto: %s already exists; pass --force to replace it" % exc, file=sys.stderr)
            return 1
        except ValueError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("wrote ontology %r to %s" % (args.name, path))
        if problems:
            print("  %d problem(s) the self-check found:" % len(problems))
            for problem in problems[:10]:
                print("    %s" % problem)
            return 1
        print("  self-check clean. Use it with: oto init --ontology %s" % (args.name if not args.to else path))
        print("  The sample is %s. validated_by is empty: confirmation does not carry to a new domain."
              % ("invented, one node per class" if args.invented else "taken from the graph"))
        return 0
    if verb == "show":
        return _show(args.which[0] if args.which else None)
    return _list()


def _list():
    from ..model import ontologies
    from ..model import registry as _registry

    names = ontologies.available()
    if not names:
        print("no ontologies found")
        return 1
    print("ontologies (start from one with `oto init --ontology <name>`; `oto ontology show <name>` for one):\n")
    infos = {name: ontologies.summary(name) for name in names}
    grouped = any(info.get("domain") for info in infos.values())
    last = object()
    for name in sorted(names, key=lambda n: ((infos[n].get("domain") or "~"), n)):
        info = infos[name]
        if grouped and info.get("domain") != last:
            last = info.get("domain")
            print("%s:" % (last or "no domain"))
        problems = ontologies.self_check(name)
        state = "" if not problems else "  [%d problem(s)]" % len(problems)
        extends = ("  extends %s" % ", ".join(info["extends"])) if info["extends"] else ""
        print("  %-22s @%-3d %2d classes, %2d relations%s%s%s"
              % (name, info["release"], info["classes"], info["properties"],
                 "  (yours)" if info["origin"] == ontologies.USER else "", extends, state))
        if info["about"]:
            print("  %-22s %s" % ("", info["about"]))
    local = set(names)
    remote = [(where, entry) for where, entry in _registry.remote_entries() if entry["name"] not in local]
    if remote:
        print("\nin a registry, not on this machine (oto ontology add <name>):\n")
        for where, entry in remote:
            print("  %-22s @%-3d %s  [%s]" % (entry["name"], int(entry.get("release") or 1),
                                               (entry.get("summary") or "").strip(), where))
    print("\nEach installs a small sample graph, so `oto build` works immediately.")
    print("Your own go in %s, written by `oto ontology export`; a directory path also works."
          % ontologies.user_dir())
    return 0


def _print_diff(report):
    from ..model import vocabulary as vocab

    head = "ontology %s: this project started from release %s" % (report["name"], report["recorded"])
    upstream = "the engine" if report["where"] == "engine" else "the registry %s" % report["where"]
    if report["current"] == report["recorded"]:
        print(head + "; %s holds the same release. Nothing upstream to take." % upstream)
        return
    print(head + "; %s holds release %s." % (upstream, report["current"]))
    if report["changelog"]:
        print("\nsince then, the ontology's changelog says:")
        for entry in report["changelog"]:
            print("  @%s  %s  %s" % (entry.get("release"), entry.get("at", ""), entry.get("note", "")))
    print("\nwhat changed, against %s:" % ("the release this project started from (tag %s)" % report["tag"]
                                           if report["basis"] == "tag" else "this project's accepted vocabulary (the lock)"))
    questions = report.get("questions") or {}
    if not report["changes"] and not any(report["rules"].values()) and not any(questions.values()):
        print("  nothing that touches the vocabulary, the rules or the questions")
    for change in report["changes"]:
        touches = (" — touches %d in this project" % change.affected) if change.affected else ""
        print("  [%-8s] %s %s: %s%s" % (change.severity, change.kind, change.subject, change.detail, touches))
    for kind in ("added", "removed", "changed"):
        for rid in report["rules"][kind]:
            print("  [%-8s] rule %s: %s" % ("breaking" if kind == "removed" else "additive", kind, rid))
    for kind in ("added", "removed", "changed", "reworded"):
        for qid in questions.get(kind) or []:
            severity = "breaking" if kind in ("removed", "changed") else ("cosmetic" if kind == "reworded" else "additive")
            print("  [%-8s] question %s: %s" % (severity, kind, qid))
    breaking = (sum(1 for c in report["changes"] if c.severity == vocab.Change.BREAKING) + len(report["rules"]["removed"])
                + len(questions.get("removed") or []) + len(questions.get("changed") or []))
    additive = (sum(1 for c in report["changes"] if c.severity == vocab.Change.ADDITIVE) + len(report["rules"]["added"])
                + len(report["rules"]["changed"]) + len(questions.get("added") or []))
    print("\n%d breaking, %d additive. Nothing was changed in this project." % (breaking, additive))
    if additive:
        print("Additive changes can be copied into ontology.config.json, rules.json and questions.json, then `oto ontology check`.")
    if breaking:
        print("A breaking change is a supersession in this project's terms: take it through a candidate, or keep your release.")


def _remote(args):
    """add, update, publish and diff: ontologies that come from, or go, somewhere else."""
    from ..model import registry as _registry
    from ..project import ProjectError

    which = list(args.which or [])
    verb = args.ontology_command
    try:
        if verb == "publish":
            if not args.to:
                print("oto: publish needs --to <registry git url>", file=sys.stderr)
                return 1
            project = None
            if not args.from_name:
                from ._common import resolve as _resolve
                project = _resolve(args)
            result = _registry.publish(args.to, project=project, ontology=args.from_name, name=args.name,
                                       summary=args.summary, from_graph=args.from_graph, note=args.note,
                                       ref=args.ref, registry_name=args.registry_name, engine=args.engine, invented=args.invented)
            print("published %s @%d to %s (registry %s) as %s, tagged %s"
                  % (result["name"], result["release"], args.to, result["registry"], result["commit"], result["tag"]))
            if result["created"]:
                print("  the registry was created: index, marketplace, README and its check workflow")
            if result["cached"]:
                print("  the local copy of the registry index was refreshed")
            print("  fetch it anywhere: oto registry add %s && oto ontology add %s" % (args.to, result["name"]))
            return 0
        if verb == "diff":
            from ._common import resolve as _resolve
            report = _registry.diff_project(_resolve(args))
            _print_diff(report)
            return 0
        if verb == "add":
            if not which:
                print("oto: add needs an ontology name, name@release, or a git URL", file=sys.stderr)
                return 1
            target = which[0]
            # a name resolves through the registries; a path is one that looks like one, never a bare
            # word that happens to be a directory here
            looks_like_path = os.sep in target or (os.altsep and os.altsep in target) or target.startswith((".", "~"))
            if "://" in target or target.startswith("git@") or (looks_like_path and os.path.isdir(os.path.expanduser(target))):
                dest, manifest = _registry.fetch_url(os.path.expanduser(target), path=args.path, ref=args.ref, force=args.force)
            else:
                name, release = _registry.split_release(target)
                dest, manifest = _registry.fetch(name, release=release, force=args.force)
            print("added %s @%d -> %s" % (manifest["name"], manifest["release"], dest))
            if manifest.get("registry"):
                print("  from registry %s at %s" % (manifest["registry"], manifest.get("commit")))
            else:
                print("  from %s at %s" % (manifest["source"], manifest.get("commit")))
            print("  use it: oto init --ontology %s@%d" % (manifest["name"], manifest["release"]))
            return 0
        # update
        changed = _registry.update(which[0] if which else None)
        if not changed:
            print("every fetched ontology is at its registry's current release")
        for name, old, new in changed:
            print("updated %s @%s -> @%s" % (name, old, new))
        return 0
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1


def _show(name):
    """One ontology in full: manifest, what it composes, what the composition changed, its checks."""
    from ..model import ontologies
    from ..model import ontology_compose as _compose

    if not name:
        print("oto: show needs a name: oto ontology show <name>", file=sys.stderr)
        return 1
    if ontologies.dir_for(name) is None:
        print("oto: unknown ontology %r. Available: %s" % (name, ", ".join(ontologies.available()) or "none"),
              file=sys.stderr)
        return 1
    manifest = ontologies.manifest_for(name)
    print("%s @%d  (%s%s)" % (name, manifest["release"], ontologies.origin(name), ontologies.dir_for(name) and
                              (", " + ontologies.dir_for(name)) if ontologies.origin(name) == ontologies.PATH else ""))
    if manifest.get("summary"):
        print("  %s" % manifest["summary"])
    if manifest.get("domain"):
        from ..model import ontology_manifest as _om
        note = _om.domain_note(manifest["domain"])
        print("  domain:   %s%s" % (manifest["domain"], ("  (%s)" % note) if note else ""))
    print("  manifest: %s" % ("manifest.json" if manifest.get("_declared") else "none (defaults)"))
    if manifest.get("engine"):
        print("  engine:   %s" % manifest["engine"])
    if manifest.get("maintainer"):
        print("  by:       %s" % manifest["maintainer"])
    print("  carries:  %s" % ", ".join(manifest.get("carries") or []))
    try:
        result = ontologies.composed(name)
    except ontologies.OntologyError as exc:
        print("\n  cannot compose: %s" % exc)
        return 1
    config = result["config"]
    report = result["report"]
    print("  extends:  %s" % (" -> ".join(report["parts"][:-1]) if len(report["parts"]) > 1 else "nothing"))
    print("\ncomposed: %d classes, %d relations, %d typed attribute(s), %d rule(s), %d sample node(s)%s%s%s%s%s"
          % (len(config.get("classes") or {}), len(config.get("properties") or {}),
             sum(len(v or {}) for v in (config.get("attributes") or {}).values()), len(result["rules"]),
             len(result["sample"].get("nodes") or []),
             ", %d lexicon entr%s" % (len(result["lexicon"]["entries"]), "y" if len(result["lexicon"]["entries"]) == 1 else "ies") if result["lexicon"] else "",
             ", an interview" if result["interview"] else "",
             ", a guide" if result.get("guide") else "",
             ", %d action(s)" % len(result["actions"]) if result.get("actions") else "",
             ", %d gold pattern(s)" % len(result["gold"]) if result["gold"] else ""))
    for line in _compose.report_lines(report):
        print("  %s" % line)
    print("\nclasses: %s" % ", ".join(config.get("classes") or {}))
    if manifest.get("changelog"):
        print("\nchangelog:")
        for entry in sorted(manifest["changelog"], key=lambda e: -int(e.get("release", 0))):
            print("  @%s  %s  %s" % (entry.get("release"), entry.get("at", ""), entry.get("note", "")))
    problems = ontologies.self_check(name)
    print("\nself-check: %s" % ("clean" if not problems else "%d problem(s)" % len(problems)))
    for problem in problems[:20]:
        print("  - %s" % problem)
    return 0 if not problems else 1


def options(parser):
    """The catalog's options, added to the `oto ontology` parser."""
    parser.add_argument("which", nargs="*", default=None,
                        help="show: a name; add: a name, name@release or git URL; update: a name")
    parser.add_argument("--path", default=None, help="for add <url>: the ontology's directory inside the repository")
    parser.add_argument("--ref", default=None, help="for add <url> and publish: a branch or tag")
    parser.add_argument("--note", default=None, help="for publish: the changelog entry for this release")
    parser.add_argument("--registry-name", dest="registry_name", default=None,
                        help="for publish into an empty repository: the registry's name")
    parser.add_argument("--engine", default=None, help="for publish: the engine repository the registry's check workflow installs")
    parser.add_argument("--name", default=None, help="the ontology's name, for export and publish")
    parser.add_argument("--to", default=None, help="for export: the directory to write under (default: your "
                                                    "ontology directory); for publish: the registry's git URL")
    parser.add_argument("--summary", default=None, help="one line saying what the vocabulary covers")
    parser.add_argument("--from-graph", dest="from_graph", type=int, default=None,
                        help="for export and publish: cap the sample at N nodes of the graph, round-robin across "
                             "classes (default: the whole graph); refused if the privacy scan blocks it")
    parser.add_argument("--invented", action="store_true",
                        help="for export and publish: ship the synthetic sample (one node per class) instead of the graph")
    parser.add_argument("--force", action="store_true", help="for export and add: replace an existing ontology of that name")
