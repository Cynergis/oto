# -*- coding: utf-8 -*-
"""OTO command line.

One module per command, in the order a project moves through them:

    init.py        oto init                     create a project, optionally from an ontology
    ingest.py      oto ingest, oto figures, oto survey   raw documents into the corpus, and a map of it
    ontology.py    oto ontology                 the project's vocabulary, and the catalog (catalog.py)
    lexicon.py     oto lexicon                  words mapped to entities: suggested by embeddings, accepted by a person
    registry.py    oto registry                 the registries ontologies and packs are fetched from
    pack.py        oto pack                     the extension a person installs: an ontology, skills, views (pack_catalog.py)
    rules.py       oto rules                    validate, dry-run, diff and accept the rules
    capture.py     oto capture                  what someone said, as a dated source document in the inbox
    clipboard.py   oto clipboard                the selected or copied text, as data for the conversation
    deploy.py      oto deploy                   the deploy config, checked; what each environment holds
    connectors.py  oto connectors               the stores a build publishes to, and the conformance kit
    curate.py      oto curate                   gated changes to the curated graph, batches via add
    decide.py      oto decide                   a named person moves a decision attribute: readiness, a confirmation
    draft.py       oto draft                    a model drafts one document's proposal (optional extra)
    vet.py         oto vet                      audit citations against the corpus
    build.py       oto build, oto clean, oto verify
    query.py       oto query, oto serve         ask, or serve over JSON-RPC
    status.py      oto status                   where the project is, and the next step
    lock.py        oto lock                     the engine, plugins and ontologies a project is built with
    sandbox.py     oto sandbox                  Claude Code with OTO in a Docker sandbox, for Claude Desktop or a terminal
    bench.py       oto bench                    measure answer quality
    feedback.py    oto feedback                 a complaint becomes a gold question
    publishable.py oto publishable              no client name or credential in a repository about to be published

Each exposes `register(sub)` to add its parsers, and a `cmd_*` handler per command. A pack's command (oto arch, oto work, oto data,
oto policy, ...) lives in the pack's own code/, a pack of the registry (ADR-0010, ADR-0011), and is discovered from the pack's manifest (ADR-0006). The handlers
import what they need lazily, so `oto --help` and `oto version` start without loading the engine.
"""
import argparse
import importlib
import sys

from .. import __version__
from ..project import ProjectError
from . import audit, bench, build, capture, clipboard, connectors, curate, decide, deploy, draft, feedback, graphs, ingest, init, lexicon, lock, ontology, pack, preview, publish, publishable, query, registry, rules, sandbox, status, tools, vet

# The core and the packs (ADR-0006). The core is the knowledge graph's lifecycle with its tools and
# its deploy; these are its commands. A pack's command comes from the pack's manifest
# (`provides.commands`, oto/extensions.py), is discovered from every pack the machine has, works only
# on a project whose vocabulary composes its pack, and says so otherwise. `oto --help` draws the line.
CORE_COMMANDS = (init, status, lock, sandbox, ingest, capture, clipboard, ontology, lexicon, pack, registry, rules, tools, curate, deploy,
                 connectors, draft, vet, build, preview, query, publish, publishable, bench, feedback, audit, graphs, decide)


def pack_commands():
    """[{name, module, label, pack}] the packs on this machine provide, from their manifests."""
    from .. import extensions
    return extensions.commands()


def _pack_modules(found):
    from .. import extensions
    modules = []
    for command in found:
        try:
            modules.append(extensions._load(command["module"], command["pack"]))
        except extensions.ExtensionError as exc:
            print("oto: %s" % exc, file=sys.stderr)
    return modules


_FOUND = pack_commands()
COMMANDS = CORE_COMMANDS + tuple(_pack_modules(_FOUND))

GROUPS = {
    "core": ("init", "status", "lock", "sandbox", "ingest", "capture", "clipboard", "ontology", "lexicon", "pack", "registry", "rules", "tools",
             "curate", "decide", "deploy", "connectors", "draft", "vet", "build", "preview", "query", "publish", "publishable", "bench",
             "feedback", "audit", "graph", "version"),
    "packs": tuple((c["name"], c["label"]) for c in _FOUND),
}


def _epilog(found):
    lines = ["core: the knowledge graph, its tools and its deploy",
             "  " + ", ".join(GROUPS["core"]),
             "",
             "packs: each works on a project whose vocabulary composes its pack (ADR-0006)"]
    if found:
        width = max(len(c["name"]) for c in found)
        for c in found:
            lines.append("  %-*s  %s" % (width, c["name"], c["label"]))
    else:
        lines.append("  none on this machine")
    return "\n".join(lines)


def cmd_version(args):
    print("oto %s" % __version__)
    return 0


def main(argv=None):
    found = pack_commands()
    parser = argparse.ArgumentParser(prog="oto", description="OTO: a temporal knowledge graph built from your documents, served to agents, deployed like code.",
                                     epilog=_epilog(found), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    for command in CORE_COMMANDS + tuple(_pack_modules(found)):
        command.register(sub)
    sub.add_parser("version", help="print the version").set_defaults(func=cmd_version)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except ProjectError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1

