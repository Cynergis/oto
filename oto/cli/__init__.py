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
    data.py        oto data                     the data layer: a store's schema, lineage and usage read in; a meaning drafted (skeleton) and confirmed by a person
    arch.py        oto arch                     the architecture graph: a CALM model in, through the gates, and back out
    ddd.py         oto ddd                      the factory's domain graph: an event-storming board in, through the capture form
    decide.py      oto decide                   a named person moves a decision attribute: readiness, a confirmation
    factory.py     oto factory                  the factory's inputs from the graph: a component's spec, the build plan
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

Each exposes `register(sub)` to add its parsers, and a `cmd_*` handler per command. The handlers
import what they need lazily, so `oto --help` and `oto version` start without loading the engine.
"""
import argparse
import sys

from .. import __version__
from ..project import ProjectError
from . import arch, audit, bench, build, capture, clipboard, connectors, curate, data, ddd, decide, deploy, draft, factory, feedback, graphs, ingest, init, lexicon, lock, ontology, pack, preview, publish, publishable, query, registry, rules, sandbox, status, tools, vet, work

COMMANDS = (init, status, lock, sandbox, ingest, capture, clipboard, ontology, lexicon, pack, registry, rules, tools, curate, data, deploy, connectors, draft, vet, build, preview, query, publish, publishable, bench, feedback, work, audit, graphs, arch, ddd, decide, factory)


def cmd_version(args):
    print("oto %s" % __version__)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="oto", description="OTO")
    sub = parser.add_subparsers(dest="command")
    for command in COMMANDS:
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

