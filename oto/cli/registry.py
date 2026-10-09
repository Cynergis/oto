# -*- coding: utf-8 -*-
"""`oto registry`: the registries this machine fetches ontologies from, and the check a registry
runs on itself.

    oto registry add <git url> [--as <name>] [--ref <branch|tag>]
    oto registry list
    oto registry remove <name>
    oto registry refresh [<name>]
    oto registry check [<dir>]        in a registry checkout: the index matches the directories
    oto registry site [<dir>] [--out <dir>]   the catalog: a static site to browse before installing

A registry lists ontologies today and will list packs as well, which is why its verbs live under
their own command rather than under `oto ontology`.
"""
import os
import sys


def _print_product_types(rows, where):
    """What kinds of product can be specified: the ontologies and packs that declare a product type."""
    if not rows:
        print("no product type %s: a pack declares one with `product_type` in its manifest" % where)
        return 0
    print("product types (the first question of a product: which kind?):\n")
    for product_type, name, release, found, summary in rows:
        print("  %-14s %-22s @%-3d %s" % (product_type, name, int(release or 1), found))
        if summary:
            print("  %-14s %-22s %s" % ("", "", summary.strip()))
    return 0


def _counts(index):
    o = len(index.get("ontologies") or [])
    p = len(index.get("packs") or [])
    return "%d ontolog%s, %d pack%s" % (o, "y" if o == 1 else "ies", p, "" if p == 1 else "s")


def cmd_registry(args):
    from ..model import registry as _registry
    from ..project import ProjectError

    which = list(args.which or [])
    verb = args.registry_command
    try:
        if verb == "add":
            if not which:
                print("oto: registry add needs a git URL", file=sys.stderr)
                return 1
            record = _registry.add_registry(which[0], name=args.as_name, ref=args.ref)
            print("registry %s: %s at %s" % (record["name"], _counts(record["index"]), record["commit"]))
            for kind, key in (("ontology", "ontologies"), ("pack", "packs")):
                for entry in record["index"].get(key) or []:
                    print("  %-9s %-22s @%-3d %s" % (kind, entry["name"], int(entry.get("release") or 1), (entry.get("summary") or "").strip()))
            return 0
        if verb == "list" and args.product_types:
            return _print_product_types(_registry.product_types(local=False), "in a registry")
        if verb == "list":
            registries = _registry.load_registries()
            if not registries:
                print("no registries; add one: oto registry add <git url>")
                return 0
            for record in registries:
                print("%-14s %s  (%s, fetched %s at %s)"
                      % (record["name"], record["url"], _counts(record.get("index") or {}),
                         record.get("fetched_at", "?"), record.get("commit", "?")))
            print("\nrecorded in %s" % _registry.registries_path())
            return 0
        if verb == "remove":
            if not which:
                print("oto: registry remove needs a name", file=sys.stderr)
                return 1
            _registry.remove_registry(which[0])
            print("removed registry %s; ontologies already fetched from it stay" % which[0])
            return 0
        if verb == "refresh":
            for record in _registry.refresh(which[0] if which else None):
                print("refreshed %s at %s" % (record["name"], record["commit"]))
            return 0
        if verb == "plugin":
            if not which or not args.to:
                print("oto: registry plugin needs a plugin name and --to <registry url> (and --repo owner/name, or --remove)", file=sys.stderr)
                return 1
            result = _registry.register_plugin(args.to, which[0], repo=args.repo, url=args.url, plugin_ref=args.plugin_ref,
                                               path=args.path, version=args.version, description=args.description,
                                               category=args.category, ref=args.ref, registry_name=args.registry_name,
                                               engine=args.engine, remove=args.remove)
            print("%s plugin %s in registry %s as %s" % ("removed" if args.remove else "listed", result["name"], result["registry"], result["commit"]))
            print("  in Claude Code: /plugin marketplace add %s, then /plugin install %s@%s" % (args.to, result["name"], result["registry"]))
            return 0
        if verb == "site":
            from .. import catalog as _catalog
            root = os.path.abspath(which[0] if which else ".")
            out, report = _catalog.write(root, out=args.out, url=args.url)
            print("catalog: %d pack(s) (%d drawn), %d ontolog%s -> %s"
                  % (report["packs"], report["drawn"], report["ontologies"], "y" if report["ontologies"] == 1 else "ies", out))
            for problem in report["problems"]:
                print("  - %s" % problem)
            return 1 if report["problems"] else 0
        # check
        root = os.path.abspath(which[0] if which else ".")
        index = _registry.read_index(root)
        problems = _registry.index_problems(index, root)
        if problems:
            print("registry %s: %d problem(s)" % (index.get("name"), len(problems)))
            for problem in problems:
                print("  - %s" % problem)
            return 1
        print("registry %s: %s, index matches the directories" % (index["name"], _counts(index)))
        return 0
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1


def register(sub):
    registry = sub.add_parser("registry", help="the registries this machine fetches ontologies from")
    registry.add_argument("registry_command", nargs="?", default="list",
                          choices=["add", "list", "remove", "refresh", "check", "site", "plugin"],
                          help="add <git url> registers one; list (default) shows them; remove <name> forgets one "
                               "(what was fetched from it stays); refresh [<name>] re-reads the index; "
                               "check [<dir>] verifies a registry checkout: the index matches the directories; "
                               "site [<dir>] generates the catalog, a static site, from a registry checkout")
    registry.add_argument("which", nargs="*", default=None,
                          help="add: a git URL; remove and refresh: a registry name; check: the checkout (default .)")
    registry.add_argument("--to", default=None, help="for plugin: the registry's git URL")
    registry.add_argument("--repo", default=None, help="for plugin: the plugin's GitHub repository, owner/name")
    registry.add_argument("--plugin-url", dest="url", default=None, help="for plugin: the plugin's git URL when not on GitHub")
    registry.add_argument("--plugin-ref", dest="plugin_ref", default=None, help="for plugin: a branch or tag of the plugin's repository")
    registry.add_argument("--path", default=None, help="for plugin: the plugin's directory inside its repository")
    registry.add_argument("--version", default=None, help="for plugin: the version the marketplace lists")
    registry.add_argument("--description", default=None, help="for plugin: one line for the marketplace")
    registry.add_argument("--category", default=None, help="for plugin: the marketplace category")
    registry.add_argument("--remove", action="store_true", help="for plugin: delist it")
    registry.add_argument("--registry-name", dest="registry_name", default=None, help="for plugin into an empty repository: the registry's name")
    registry.add_argument("--engine", default=None, help="for plugin into an empty repository: the engine repository the check workflow installs")
    registry.add_argument("--product-types", dest="product_types", action="store_true",
                          help="for list: the kinds of product the registries' packs specify (manifest `product_type`)")
    registry.add_argument("--as", dest="as_name", default=None,
                          help="for add: register it under this name instead of the name its index declares")
    registry.add_argument("--ref", default=None, help="for add: a branch or tag to read the index from")
    registry.add_argument("--out", default=None, help="for site: the directory to write (default: <dir>/site)")
    registry.add_argument("--url", default=None, help="for site: what a person types to add this registry (default: the checkout's git remote)")
    registry.set_defaults(func=cmd_registry)
