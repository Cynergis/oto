# -*- coding: utf-8 -*-
"""The data semantic layer's commands (roadmap Epic C). This release: introspection (C1).

    oto data introspect [--connector sqlite|postgres|bigquery] [--path <store>] [--store datastore.<id>] --at YYYY-MM-DD

reads a store's catalog through an overlay connector (`--path` for a SQLite file; Postgres and
BigQuery read their connection from project.config.json or the environment) and writes two things: a schema document
(`build/documents/schema-<store>.md`, kept in `archive/` too), one line per table and per column,
and a proposal (`proposals/schema-<store>.json`) in the data vocabulary: a `Table` per table or view,
a `Column` per column with its type, nullability and key, `column_of` and `references` edges, the
table `part_of` the data store, and a `Document` node for the snapshot. The store is the estate's:
a `DataStore` the graph already holds (and that runs in an environment, as the estate's shape
says), so the data layer describes what the architecture declares and never a store of its own. Every node quotes its own line of the document as evidence, so
`oto curate check` can hold the citation. The proposal then goes through the gates like any other
change (`oto curate add`, `check`, `apply`), and the apply is what the audit log records.

The catalog says nothing about meaning: no description is proposed, so every table and column reads
as a `draft` (the vocabulary's default) until an agent drafts one and a person confirms it (C2).
Introspecting an unchanged store again proposes the same facts, which the merge re-attests and
does not duplicate.
"""
import datetime
import json
import os
import re

from .project import ProjectError

TABLE, COLUMN, STORE, DOCUMENT = "Table", "Column", "DataStore", "Document"
DOC_KIND = "schema"


class DataError(ProjectError):
    """A refusal, in words the person can act on."""


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def store_slug(store_id):
    """datastore.ledger -> ledger."""
    return _slug(store_id.split(".", 1)[1] if "." in store_id else store_id)


def table_id(store, table):
    return "table.%s-%s" % (store, _slug(table))


def column_id(store, table, column):
    return "column.%s-%s-%s" % (store, _slug(table), _slug(column))


def column_line(column):
    """The one line of the schema document that states a column, quoted as the column's evidence:
    name, type, then what holds of it."""
    parts = [column["name"], column["type"]]
    if not column.get("nullable", True):
        parts.append("not null")
    if column.get("key") == "primary":
        parts.append("primary key")
    if column.get("references"):
        parts.append("references %s" % column["references"])
    return " ".join(parts)


def table_line(table):
    return "%s (%s)" % (table["name"], table["kind"])


def document(schema, connector_name, at):
    """The schema snapshot as markdown: the title, then a section per table with its columns."""
    title = "Schema of %s" % schema["store"]
    lines = ["# %s" % title, "", "Read from the %s catalog on %s by `oto data introspect`. One line per table and per column: "
             "name, type, then what holds of it. Each fact in the graph quotes its line here." % (connector_name, at), ""]
    for table in schema["tables"]:
        lines.append("## %s" % table_line(table))
        lines.append("")
        for column in table["columns"]:
            lines.append("- %s" % column_line(column))
        lines.append("")
    return title, "\n".join(lines).rstrip() + "\n"


def propose(schema, doc, store_id, at, connector_name):
    """The proposal: {"source_doc", "as_of", "nodes", "edges"}. A `references` edge only when the
    referenced table is in this catalog."""
    store = store_slug(store_id)
    title, _text = document(schema, connector_name, at)
    nodes, edges = [], []
    known = {t["name"] for t in schema["tables"]}
    nodes.append({"id": "document.%s" % doc, "type": DOCUMENT, "label": title, "summary": "The %s catalog of %s, as `oto data introspect` read it; the date is the fact's own." % (connector_name, schema["store"]),
                  "attributes": {"kind": DOC_KIND}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": title}]})
    for table in schema["tables"]:
        tid = table_id(store, table["name"])
        nodes.append({"id": tid, "type": TABLE, "label": table["name"], "summary": "%s %s of %s, %d column(s)." % (
            "A" if table["kind"] == "table" else "A", table["kind"], schema["store"], len(table["columns"])),
            "attributes": {"kind": table["kind"]}, "valid_from": at,
            "evidence": [{"doc": doc, "where": "catalog", "quote": table_line(table)}]})
        edges.append({"from": tid, "rel": "part_of", "to": store_id})
        for column in table["columns"]:
            cid = column_id(store, table["name"], column["name"])
            attributes = {"type": column["type"], "nullable": bool(column.get("nullable", True))}
            if column.get("key"):
                attributes["key"] = column["key"]
            nodes.append({"id": cid, "type": COLUMN, "label": column["name"], "summary": "Column %s of %s: %s." % (column["name"], table["name"], column["type"]),
                          "attributes": attributes, "valid_from": at,
                          "evidence": [{"doc": doc, "where": table["name"], "quote": column_line(column)}]})
            edges.append({"from": cid, "rel": "column_of", "to": tid})
            if column.get("references"):
                other_table, _dot, other_column = column["references"].partition(".")
                if other_table in known and other_column:
                    edges.append({"from": cid, "rel": "references", "to": column_id(store, other_table, other_column)})
    return {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": edges}


def _graph_ids(project):
    from .curate import session as _session
    nodes = list(_session.live(project).get("nodes") or [])
    if _session.exists(project):
        nodes += list(_session.candidate(project).get("nodes") or [])
    return {n.get("id") for n in nodes if n.get("id")}


def introspect(project, connector_name="sqlite", path=None, store_id=None, at=None, settings=None):
    """Read the catalog, write the document and the proposal. Returns {"doc", "document", "archive",
    "proposal", "store", "tables", "columns", "read_at"}."""
    from . import connectors as _connectors
    if not at or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(at)):
        raise DataError("--at YYYY-MM-DD is required: the date the catalog was read is never defaulted")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    classes = vocabulary.get("classes") or {}
    if TABLE not in classes or COLUMN not in classes:
        raise DataError("the vocabulary declares no Table and Column: the data ontology does (oto init --ontology data, or compose it)")
    connector = _connectors.get(connector_name)
    if connector is None or "overlay" not in (connector.MANIFEST.get("modes") or []):
        overlays = [n for n in _connectors.available() if "overlay" in _connectors.get(n).MANIFEST.get("modes", [])]
        raise DataError("no overlay connector %r; one of %s" % (connector_name, ", ".join(overlays) or "none"))
    if settings is None:
        if path is not None:
            settings = {"path": path}
        elif connector_name == "sqlite":
            settings = {"path": project.layout.database}
            if not os.path.exists(settings["path"]):
                raise DataError("the project has no built store at %s yet: run `oto build`, or pass --path <store>"
                                % os.path.relpath(settings["path"], project.data))
        else:
            settings = connector.settings(project)
    session = connector.connect(settings)
    try:
        try:
            schema = connector.introspect(session)
        except FileNotFoundError as exc:
            raise DataError(str(exc))
    finally:
        connector.close(session)
    store_id = store_id or "datastore.%s" % _slug(schema["store"])
    if not store_id.startswith("datastore."):
        raise DataError("--store names the DataStore node the tables are part of: datastore.<id>, not %r" % store_id)
    graph_ids = _graph_ids(project)
    if store_id not in graph_ids:
        raise DataError("the graph holds no %s. The data layer describes a store the estate declares: record the DataStore "
                        "(and the environment it runs in) first, or name one the graph holds with --store datastore.<id>" % store_id)
    doc = "schema-%s" % store_slug(store_id)
    title, text = document(schema, connector_name, at)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    proposal = propose(schema, doc, store_id, at, connector_name)
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "store": store_id,
            "tables": len(schema["tables"]), "columns": sum(len(t["columns"]) for t in schema["tables"]),
            "read_at": datetime.date.today().isoformat()}
