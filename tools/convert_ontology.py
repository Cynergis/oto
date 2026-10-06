#!/usr/bin/env python3
"""Rewrite an ontology directory written before the semantic layer into the form the engine reads.

    python tools/convert_ontology.py <ontology dir> [--namespace <iri>] [--note <text>] [--dry-run]

What it does, and says:
  - every declaration becomes an object: a class {definition}, a relation {domain, range, inverse,
    definition}, an attribute and a temporal term {type, definition}
  - the manifest gets a `namespace` (default https://cynergis.ai/ont/<name>#), a bumped release
    and a changelog entry; a directory without a manifest gets one
  - the `_about` note stops describing the list form
  - the result is self-checked the way `oto init` would check it

Nothing else is invented: no labels (a term is read by its name unless one is written), no
hierarchy, no schemes. Those are decisions for the person who owns the ontology. The directory's
previous files are copied to <parent>-before-convert/<name>/ unless --dry-run.
"""
import argparse
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from oto.model import ontologies, ontology_manifest as _manifest, vocabulary as _vocab  # noqa: E402

ABOUT_OLD = "Property value is [Domain, Range, inverse_or_null, description]. Use A|B for a union."
ABOUT_NEW = "A relation is {domain, range, inverse, definition}. Use A|B for a union."


def convert_config(config):
    """The vocabulary in the object form; what was already in it is left as it is."""
    changed = []
    classes = {}
    for name, spec in (config.get("classes") or {}).items():
        if isinstance(spec, str):
            classes[name] = {"definition": spec}
            changed.append("class %s" % name)
        else:
            classes[name] = spec
    config["classes"] = classes
    properties = {}
    for name, spec in (config.get("properties") or {}).items():
        if isinstance(spec, (list, tuple)):
            domain, rng, inverse, definition = (list(spec) + [None] * 4)[:4]
            new = {}
            if domain:
                new["domain"] = domain
            if rng:
                new["range"] = rng
            if inverse:
                new["inverse"] = inverse
            new["definition"] = definition or ""
            properties[name] = new
            changed.append("relation %s" % name)
        else:
            properties[name] = spec
    config["properties"] = properties
    for section in ("attributes",):
        for kind, declared in list((config.get(section) or {}).items()):
            for attr, spec in list((declared or {}).items()):
                if isinstance(spec, (list, tuple)):
                    declared[attr] = {"type": spec[0], "definition": spec[1] if len(spec) > 1 else ""}
                    changed.append("attribute %s.%s" % (kind, attr))
    for name, spec in list((config.get("temporal") or {}).items()):
        if isinstance(spec, (list, tuple)):
            config["temporal"][name] = {"type": spec[0], "definition": spec[1] if len(spec) > 1 else ""}
            changed.append("temporal %s" % name)
    if ABOUT_OLD in (config.get("_about") or ""):
        config["_about"] = config["_about"].replace(ABOUT_OLD, ABOUT_NEW)
        changed.append("_about")
    return changed


def convert(directory, namespace=None, note=None, dry_run=False):
    directory = os.path.abspath(directory)
    config_path = os.path.join(directory, ontologies.CONFIG_NAME)
    if not os.path.exists(config_path):
        raise SystemExit("%s holds no %s" % (directory, ontologies.CONFIG_NAME))
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    name = os.path.basename(directory.rstrip(os.sep))
    manifest = _manifest.read(directory, fallback_summary=(config.get("_summary") or "").strip())
    namespace = namespace or manifest.get("namespace") or "https://cynergis.ai/ont/%s#" % name

    changed = convert_config(config)
    report = ["%s:" % directory, "  declarations rewritten: %d" % len(changed)]
    if not manifest.get("_declared"):
        report.append("  manifest.json written (there was none)")
    if manifest.get("namespace") != namespace:
        report.append("  namespace: %s" % namespace)
        manifest["namespace"] = namespace
    manifest["release"] = int(manifest.get("release") or 0) + 1 if manifest.get("_declared") else 1
    manifest["changelog"] = [{"release": manifest["release"], "at": datetime.date.today().isoformat(),
                              "note": note or "Rewritten in the engine's form (every declaration an object) and given its namespace."}] \
        + list(manifest.get("changelog") or [])
    manifest["carries"] = _manifest.detect_carries(directory)
    report.append("  release: %d" % manifest["release"])

    if not dry_run:
        # Beside the catalog, not in it: a copy inside would be listed as an ontology and fail.
        backup = os.path.join(os.path.dirname(directory.rstrip(os.sep)) + "-before-convert", name)
        if not os.path.exists(backup):
            shutil.copytree(directory, backup)
            report.append("  previous files kept at %s" % backup)
        with open(config_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        _manifest.write(directory, manifest)
        problems = ontologies.self_check(directory)
    else:
        problems = _vocab.shape_problems(config) + _vocab.hierarchy_problems(config) + _vocab.scheme_problems(config)
    if problems:
        report.append("  NOT USABLE YET:")
        report += ["    - %s" % p for p in problems]
    else:
        report.append("  usable: the self-check passes")
    return report, not problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("directories", nargs="+", help="ontology directories to rewrite")
    ap.add_argument("--namespace", help="the IRI the terms live under (default: https://cynergis.ai/ont/<name>#)")
    ap.add_argument("--note", help="the changelog note (default says what was done)")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args(argv)
    ok = True
    for directory in args.directories:
        report, usable = convert(directory, args.namespace, args.note, args.dry_run)
        print("\n".join(report))
        ok = ok and usable
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
