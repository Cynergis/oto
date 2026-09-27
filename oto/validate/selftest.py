# -*- coding: utf-8 -*-
"""Greenfield self-test.

Proves the engine is domain agnostic without needing any real corpus: it creates a throwaway project
for an invented domain, authors two classes and two nodes, compiles every layer, then asserts the
database answers and the integrity gate is clean.

Run it after changing the pipeline, and as a post-install check:

    oto verify
"""
import json
import os
import shutil
import sqlite3
import tempfile

SLUG = "selftest"


def _author(root):
    """Write a minimal, invented domain: two classes, two nodes, one edge. Returns the graph."""
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["classes"] = {"Machine": "A physical machine.", "Site": "A place where machines run."}
    cfg["properties"] = {"installed_at": ["Machine", "Site", "hosts", "Where a machine runs."]}
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    stamp = {"as_of": "2026-01-01", "valid_from": "2026-01-01",
             "source_doc": "handbook", "status": "current", "sources": ["handbook"]}
    graph = {
        "nodes": [
            dict(id="machine.press-01", type="Machine", label="Press 01", aliases=["Press One"],
                 summary="A stamping press.", attributes={}, tags=["machine"], **stamp),
            dict(id="site.north", type="Site", label="North Plant", aliases=["North"],
                 summary="The northern plant.", attributes={}, tags=["site"], **stamp),
        ],
        "edges": [{"from": "machine.press-01", "rel": "installed_at", "to": "site.north"}],
    }
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    return graph


def verify():
    """Return True when the greenfield path works end to end."""
    from ..project import Project
    from ..scaffold import init

    root = tempfile.mkdtemp(prefix="oto_verify_")
    failures = []
    try:
        init(root, slug=SLUG, name="OTO Self Test")
        _author(root)
        project = Project.standard(root)
        layout = project.layout

        # One authored note and one extracted document, so both indexed roots are exercised.
        os.makedirs(layout.corpus, exist_ok=True)
        with open(os.path.join(layout.corpus, "handbook.md"), "w", encoding="utf-8") as f:
            f.write("# Handbook\n\nPress 01 is installed at the North Plant.\n")
        os.makedirs(layout.notes, exist_ok=True)
        with open(os.path.join(layout.notes, "01-overview.md"), "w", encoding="utf-8") as f:
            f.write("# Overview\n\nThe north plant runs one stamping press.\n")

        import importlib
        for module_path in ("oto.compile.knowledge", "oto.compile.ontology",
                            "oto.compile.semantic", "oto.targets.sqlite"):
            importlib.import_module(module_path).run(project)

        db = layout.database
        if not os.path.exists(db):
            failures.append("no database produced at %s" % db)
        else:
            con = sqlite3.connect(db)
            nodes = con.execute("select count(1) from nodes").fetchone()[0]
            if nodes != 2:
                failures.append("expected 2 nodes, got %d" % nodes)
            edges = con.execute("select count(1) from edges").fetchone()[0]
            if edges != 1:
                failures.append("expected 1 edge, got %d" % edges)
            hits = con.execute("select label from node_fts where node_fts match 'press'").fetchall()
            if not hits:
                failures.append("full-text search for 'press' returned nothing")
            # The AUTHORED note must be indexed too, not just the generated pages.
            noted = con.execute("select path from docs where path like '%01-overview%'").fetchall()
            if not noted:
                failures.append("the authored note under notes/ was not indexed")
            identity = con.execute("select value from meta where key='build_seq'").fetchone()
            if not identity:
                failures.append("no build_seq stamp")
            con.close()

        # The generated ontology must carry THIS domain's vocabulary, not anything inherited.
        ontology_md = os.path.join(layout.ontology, "ontology.md")
        if not os.path.exists(ontology_md):
            failures.append("no ontology.md produced")
        else:
            with open(ontology_md, encoding="utf-8") as f:
                text = f.read()
            for expected in ("Machine", "Site", "installed_at"):
                if expected not in text:
                    failures.append("ontology.md is missing the declared term %r" % expected)
    except Exception as exc:                      # noqa: BLE001 - report any failure, do not mask it
        failures.append("%s: %s" % (type(exc).__name__, exc))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if failures:
        print("\nOTO VERIFY: FAIL")
        for f in failures:
            print("  - %s" % f)
        return False
    print("\nOTO VERIFY: PASS — init, author, compile, query all work on a fresh domain.")
    return True
