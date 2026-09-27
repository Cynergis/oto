# -*- coding: utf-8 -*-
"""The catalog half of `oto pack`: the packs on this machine and in the registries.

    oto pack list                         every pack on this machine, and what a registry lists
    oto pack show <name|dir>              one in full
    oto pack add <name|name@release|url>  fetch one
    oto pack update [<name>]              re-fetch newer releases
    oto pack publish --to <registry url>  release the pack in the current directory, or --from <name>
"""
import os
import sys


def run(args):
    from ..model import packs
    from ..model import registry as _registry
    from ..project import ProjectError

    verb = args.pack_command
    which = list(args.which or [])
    try:
        if verb == "show":
            return _show(which[0] if which else None)
        if verb == "add":
            if not which:
                print("oto: add needs a pack name, name@release, or a git URL", file=sys.stderr)
                return 1
            target = which[0]
            # a name resolves through the registries; a path is one that looks like one, never a bare
            # word that happens to be a directory here
            looks_like_path = os.sep in target or (os.altsep and os.altsep in target) or target.startswith((".", "~"))
            if "://" in target or target.startswith("git@") or (looks_like_path and os.path.isdir(os.path.expanduser(target))):
                dest, manifest = _registry.fetch_url(os.path.expanduser(target), path=args.path, ref=args.ref, force=args.force, kind="pack")
            else:
                name, release = _registry.split_release(target)
                dest, manifest = _registry.fetch(name, release=release, force=args.force, kind="pack")
            onto = manifest.get("ontology") or {}
            print("added pack %s @%d -> %s" % (manifest["name"], manifest["release"], dest))
            print("  embeds the ontology %s@%s; from %s at %s"
                  % (onto.get("name"), onto.get("release"), manifest.get("registry") and ("registry %s" % manifest["registry"]) or manifest["source"], manifest.get("commit")))
            print("  use it: oto init --pack %s" % manifest["name"])
            return 0
        if verb == "update":
            changed = _registry.update(which[0] if which else None, kind="pack")
            if not changed:
                print("every fetched pack is at its registry's current release")
            for name, old, new in changed:
                print("updated pack %s @%s -> @%s" % (name, old, new))
            return 0
        if verb == "publish":
            if not args.to:
                print("oto: publish needs --to <registry git url>", file=sys.stderr)
                return 1
            source = args.from_name or (packs.dir_for(os.getcwd()) and os.getcwd())
            if not source:
                print("oto: publish needs --from <name|dir>, or a pack in the current directory", file=sys.stderr)
                return 1
            result = _registry.publish_pack(args.to, source, note=args.note, summary=args.summary, ref=args.ref,
                                            registry_name=args.registry_name, engine=args.engine)
            print("published pack %s @%d to %s (registry %s) as %s, tagged %s"
                  % (result["name"], result["release"], args.to, result["registry"], result["commit"], result["tag"]))
            if result["created"]:
                print("  the registry was created: index, marketplace, README and its check workflow")
            print("  marketplace lists the engine plugin and %d pack(s): %s" % (len(result["plugins"]), ", ".join(result["plugins"])))
            if result["cached"]:
                print("  the local copy of the registry index was refreshed")
            print("  in Claude Code: /plugin marketplace add %s, then /plugin install %s@%s" % (args.to, result["name"], result["registry"]))
            return 0
        return _list()
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1


def _list():
    from ..model import packs
    from ..model import registry as _registry

    names = packs.available()
    if names:
        print("packs on this machine (start from one with `oto init --pack <name>`; `oto pack show <name>` for one):\n")
        infos = {name: packs.summary(name) for name in names}
        grouped = any(info.get("domain") for info in infos.values())
        last = object()
        for name in sorted(names, key=lambda n: ((infos[n].get("domain") or "~"), n)):
            info = infos[name]
            if grouped and info.get("domain") != last:
                last = info.get("domain")
                print("%s:" % (last or "no domain"))
            problems = packs.check(packs.dir_for(name))
            print("  %-22s @%-3d ontology %s@%s, %d skill(s), %d view(s)%s%s"
                  % (name, info["release"], info["ontology"], info["ontology_release"], len(info["skills"]), len(info["views"]),
                     "  (fetched)" if info["origin"] == packs.FETCHED else "", "" if not problems else "  [%d problem(s)]" % len(problems)))
            if info["about"]:
                print("  %-22s %s" % ("", info["about"]))
    else:
        print("no packs on this machine (oto pack new <name> --ontology <name>, or oto pack add <name>)")
    local = set(names)
    remote = [(where, entry) for where, entry in _registry.remote_entries("pack") if entry["name"] not in local]
    if remote:
        print("\nin a registry, not on this machine (oto pack add <name>):\n")
        for where, entry in remote:
            onto = entry.get("ontology") or {}
            print("  %-22s @%-3d %s  [%s%s]" % (entry["name"], int(entry.get("release") or 1), (entry.get("summary") or "").strip(),
                                                 where, (", " + entry["domain"]) if entry.get("domain") else ""))
    print("\nYour own go in %s, written by `oto pack new`." % packs.user_dir())
    return 0


def _show(name):
    from ..model import packs

    if not name:
        print("oto: show needs a name or a directory: oto pack show <name|dir>", file=sys.stderr)
        return 1
    directory = packs.dir_for(name)
    if directory is None:
        print("oto: unknown pack %r. On this machine: %s" % (name, ", ".join(packs.available()) or "none"), file=sys.stderr)
        return 1
    manifest = packs.read(directory)
    onto = manifest.get("ontology") or {}
    print("%s @%d  (%s%s)" % (manifest["name"], manifest["release"], packs.origin(name) or packs.PATH,
                              (", " + directory) if packs.origin(name) in (packs.PATH, None) else ""))
    if manifest.get("summary"):
        print("  %s" % manifest["summary"])
    if manifest.get("domain"):
        print("  domain:   %s" % manifest["domain"])
    print("  ontology: %s@%s, from %s%s" % (onto.get("name"), onto.get("release"),
                                            ("registry " + onto["registry"]) if onto.get("registry") else onto.get("source"),
                                            (", embedded %s" % onto["embedded_at"]) if onto.get("embedded_at") else ""))
    if manifest.get("registry") or manifest.get("source"):
        print("  fetched:  from %s at %s" % (manifest.get("registry") or manifest.get("source"), manifest.get("commit")))
    if manifest.get("engine"):
        print("  engine:   %s" % manifest["engine"])
    if manifest.get("maintainer"):
        print("  by:       %s" % manifest["maintainer"])
    print("  skills:   %s" % (", ".join(packs.skills(directory)) or "none"))
    print("  views:    %s" % (", ".join(packs.views(directory)) or "none"))
    config = packs.embedded_config(directory)
    if config:
        print("\nthe ontology declares %d classes, %d relations: %s"
              % (len(config.get("classes") or {}), len(config.get("properties") or {}), ", ".join(config.get("classes") or {})))
    for note in packs.notes(directory):
        print("  note: %s" % note)
    if manifest.get("changelog"):
        print("\nchangelog:")
        for entry in sorted(manifest["changelog"], key=lambda e: -int(e.get("release", 0))):
            print("  @%s  %s  %s" % (entry.get("release"), entry.get("at", ""), entry.get("note", "")))
    problems = packs.check(directory)
    print("\ncheck: %s" % ("clean" if not problems else "%d problem(s)" % len(problems)))
    for problem in problems[:20]:
        print("  - %s" % problem)
    return 0 if not problems else 1
