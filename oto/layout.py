# -*- coding: utf-8 -*-
"""Where each artifact lives, and which of them the build owns.

The rule "never hand-edit the generated layers" was unenforceable in the original layout, because
authored and generated files shared directories. Measured on a real project: of 3,864 files in the
so-called generated layers, 3,847 were generated and 17 were not. The 17 were hand-written narrative
notes, a changelog, two reference documents and four scripts. A tool that cleared a directory would
have destroyed them, and one did during development.

The standard layout separates them, so `build/` is entirely generated and deleting it loses nothing:

    <root>/
      inbox/      raw sources, dropped in by a person; unclaimed
      processing/ claimed by an ingest run; extracted, not yet in the graph
      errors/     files a run could not extract, by run, each with a .error.json
      archive/    the graph holds them; moved here by `oto ingest complete`
      runs/       one manifest per ingest run: files, hashes, outcomes
      notes/      AUTHORED narrative markdown
      build/      GENERATED, safe to delete
        documents/  the corpus, extracted from inbox
        entities/   one page per graph node
        ontology/   ontology.md and the RDF forms
        cards/      retrieval cards
        graph/      graph JSON, CSV, N-Triples, search index
        site/       the static site: the graph payload and a view, when targeted
        <slug>.db

This is the only layout. The pre-OTO one, which kept authored and generated files together, was
read through a `--legacy` flag until it had no users left; a project from that time is moved once
with `oto init` and a copy of its graph.
"""
import os


class Layout:
    """Resolved paths for one project.

    `indexed` is ordered, because the search index records paths and its content depends on the order
    directories are walked.
    """

    def __init__(self, root, src, db_name):
        self.root = root
        self.src = src
        build = src
        self.inbox = os.path.join(root, "inbox")
        self.archive = os.path.join(root, "archive")
        self.processing = os.path.join(root, "processing")
        self.errors = os.path.join(root, "errors")
        self.runs = os.path.join(root, "runs")
        self.corpus = os.path.join(build, "documents")
        self.notes = os.path.join(root, "notes")
        self.actions = os.path.join(root, "actions")
        self.entities = os.path.join(build, "entities")
        self.ontology = os.path.join(build, "ontology")
        self.cards = os.path.join(build, "cards")
        self.graph = os.path.join(build, "graph")
        self.database = os.path.join(build, db_name)
        self.site = os.path.join(build, "site")
        self.indexed = [self.corpus, self.notes, self.entities, self.cards]

    def label(self, path):
        """The path recorded for an indexed file.

        These strings land in the search index and in the passage table, so they are part of the
        output and must be stable: relative to the project root with the `build/` prefix removed,
        so a reader sees `documents/x.md`, `notes/y.md`, `entities/z.md` regardless of where the
        build directory sits.
        """
        rel = os.path.relpath(path, self.root).replace("\\", "/")
        prefix = os.path.basename(self.src) + "/"
        return rel[len(prefix):] if rel.startswith(prefix) else rel

    # ---- what the build owns ----
    def generated(self):
        """Paths the compile stages own. Everything here may be deleted and rebuilt.

        The corpus is absent: it is produced by ingest from the inbox, not by the compile stages.
        """
        return [self.entities, self.cards, self.ontology, self.graph, self.database, self.site]

    def authored(self):
        """Paths a person writes. A build must never touch these."""
        return [self.notes]

    def sources(self):
        """The raw-file stations, in the order a file moves through them. Never touched by a build."""
        return [self.inbox, self.processing, self.errors, self.archive]

    def build_root(self):
        """The directory that is entirely generated: deleting it loses nothing."""
        return self.src

    def __repr__(self):
        return "Layout(root=%r, src=%r)" % (self.root, self.src)
