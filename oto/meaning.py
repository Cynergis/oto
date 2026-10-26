# -*- coding: utf-8 -*-
"""Meaning (roadmap C2): what a table or a column is about, drafted by an agent and confirmed by a
named person, never the other way round.

    oto data meaning --store datastore.<id> --at YYYY-MM-DD        # what has no description yet, as a skeleton proposal
    oto data meaning --check proposals/meaning-<store>.json        # the filled proposal, before the gates
    oto data confirm <table.…|column.…> --by <person> --at YYYY-MM-DD [--description "…"] [--note "…"]

The skeleton lists every table and column of the store without a description: each node with its
schema line as evidence (so the citation holds at `oto curate check`) and, apart from the nodes
under `_context`, what the catalog, the lineage and the usage say about it (type, key, what loads
it and from where, who uses it) and never a meaning. The data-meaning skill fills `description` in
one sentence per node or drops the node; `--check` refuses an empty description, a node the graph
lacks, a type that is not Table or Column, and a status other than `draft`: a proposal drafts, a
person confirms. The proposal then goes through the gates like any other change, and every
description it adds reads as a draft (DT4 lists it).

`oto data confirm` is the person's decision. It records an assertion by them, moves
`description_status` to `confirmed` (and sets the description when they state it with
`--description`) and applies under the gates, the way `oto work` records a state. The gates allow
the move because the vocabulary marks `description_status` as a decision and the node now cites the
assertion; a proposal that tries to confirm is refused as a supersession, since no new source
signed it. Confirming what is confirmed changes nothing and says so.
"""
import json
import os
import re

from .data import DataError, TABLE, COLUMN, _graph_ids, store_slug
from .curate import session as _session

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DRAFT, CONFIRMED = "draft", "confirmed"


class MeaningError(DataError):
    """A refusal, in words the person can act on."""


def _index(graph):
    return {n.get("id"): n for n in graph.get("nodes") or [] if n.get("id")}


def _edges(graph, rel):
    return [e for e in graph.get("edges") or [] if e.get("rel") == rel]


def _label(nodes, nid):
    node = nodes.get(nid) or {}
    return node.get("label") or nid


def context_of(graph, store_id):
    """{"tables": [table node, ...], "columns": {table id: [column node, ...]}, "context": {node id: {...}}}
    for the store's tables and columns, in the graph's order."""
    nodes = _index(graph)
    tables = [nodes[e["from"]] for e in _edges(graph, "part_of") if e.get("to") == store_id and nodes.get(e["from"], {}).get("type") == TABLE]
    columns = {t["id"]: [] for t in tables}
    for e in _edges(graph, "column_of"):
        if e.get("to") in columns and nodes.get(e["from"], {}).get("type") == COLUMN:
            columns[e["to"]].append(nodes[e["from"]])
    loaded_by = {}
    for e in _edges(graph, "loaded_by"):
        loaded_by.setdefault(e["from"], []).append(e["to"])
    sourced_from = {}
    for e in _edges(graph, "sourced_from"):
        sourced_from.setdefault(e["from"], []).append(e["to"])
    uses = {}
    for e in _edges(graph, "use_of"):
        uses.setdefault(e["to"], []).append(e["from"])
    used_by = {}
    for e in _edges(graph, "used_by"):
        used_by.setdefault(e["from"], []).append(e["to"])
    context = {}
    for t in tables:
        item = {"kind": (t.get("attributes") or {}).get("kind"), "columns": [c.get("label") for c in columns[t["id"]]]}
        jobs = loaded_by.get(t["id"], [])
        if jobs:
            item["loaded_by"] = [_label(nodes, j) for j in jobs]
            sources = []
            for j in jobs:
                sources += [_label(nodes, s) for s in sourced_from.get(j, [])]
            if sources:
                item["sourced_from"] = sources
        readers = []
        for u in uses.get(t["id"], []):
            readers += ["%s (%s)" % (_label(nodes, r), (nodes.get(u, {}).get("attributes") or {}).get("kind") or "?") for r in used_by.get(u, [])]
        if readers:
            item["used_by"] = readers
        context[t["id"]] = item
        for c in columns[t["id"]]:
            attributes = c.get("attributes") or {}
            entry = {"table": t.get("label"), "type": attributes.get("type"), "nullable": attributes.get("nullable")}
            if attributes.get("key"):
                entry["key"] = attributes["key"]
            for e in _edges(graph, "references"):
                if e.get("from") == c["id"]:
                    entry["references"] = _label(nodes, e["to"])
            context[c["id"]] = entry
    return {"tables": tables, "columns": columns, "context": context}


def skeleton(project, store_id, at):
    """Write proposals/meaning-<store>.json: every table and column without a description, with
    its evidence and its context. Returns {"proposal", "count", "store", "doc"}."""
    if not at or not ISO_DATE.match(str(at)):
        raise MeaningError("--at YYYY-MM-DD is required: the date the meanings are drafted is never defaulted")
    if not store_id or not str(store_id).startswith("datastore."):
        raise MeaningError("--store datastore.<id> names the DataStore whose tables are described")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        attributes = json.load(f).get("attributes") or {}
    if "description" not in (attributes.get(TABLE) or {}) or "description" not in (attributes.get(COLUMN) or {}):
        raise MeaningError("the vocabulary declares no Table and Column with a description: the data ontology does (oto init --ontology data, or compose it)")
    graph = _session.live(project)
    if store_id not in _index(graph):
        raise MeaningError("the graph holds no %s. Record the DataStore and introspect it first (oto data introspect)" % store_id)
    found = context_of(graph, store_id)
    nodes = []
    for t in found["tables"]:
        for node in [t] + found["columns"][t["id"]]:
            if (node.get("attributes") or {}).get("description"):
                continue
            nodes.append({"id": node["id"], "type": node["type"], "label": node.get("label"),
                          "attributes": {"description": "", "description_status": DRAFT},
                          "evidence": [dict(e) for e in node.get("evidence") or []]})
    store = store_slug(store_id)
    doc = "schema-%s" % store
    proposal = {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": [],
                "_context": {n["id"]: found["context"][n["id"]] for n in nodes},
                "_about": "A skeleton `oto data meaning` wrote: fill every `description` in one sentence, grounded in `_context` and the "
                          "documents under build/documents/, or drop the node; leave `description_status` as draft (a person confirms with "
                          "`oto data confirm`); then `oto data meaning --check` this file and take it through the gates."}
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "meaning-%s.json" % store)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"proposal": out, "count": len(nodes), "store": store_id, "doc": doc}


def check(project, path):
    """What is wrong with a filled meaning proposal, before the gates. Returns {"count", "problems", "empty"}."""
    if not os.path.isfile(path):
        raise MeaningError("no such proposal: %s" % path)
    with open(path, encoding="utf-8") as f:
        try:
            proposal = json.load(f)
        except ValueError as exc:
            raise MeaningError("%s is not JSON: %s" % (path, exc))
    nodes = proposal.get("nodes") if isinstance(proposal, dict) else None
    if not isinstance(nodes, list):
        raise MeaningError("%s: a proposal is {\"source_doc\", \"as_of\", \"nodes\": [...]}" % path)
    live = _index(_session.live(project))
    problems, empty = [], 0
    for n in nodes:
        nid = n.get("id") if isinstance(n, dict) else None
        if not nid:
            problems.append("a node has no id")
            continue
        if nid not in live:
            problems.append("%s: the graph lacks it; a meaning describes a table or column the catalog said (oto data introspect)" % nid)
            continue
        if live[nid].get("type") not in (TABLE, COLUMN) or n.get("type") not in (TABLE, COLUMN):
            problems.append("%s: a %s, not a Table or a Column" % (nid, live[nid].get("type")))
            continue
        attributes = n.get("attributes") or {}
        description = attributes.get("description")
        if not isinstance(description, str) or not description.strip():
            empty += 1
            problems.append("%s: empty description; fill it in one sentence, or drop the node" % nid)
        status = attributes.get("description_status", DRAFT)
        if status != DRAFT:
            problems.append("%s: description_status is %s; a proposal drafts, a person confirms with `oto data confirm %s --by <name> --at <date>`"
                            % (nid, status, nid))
        extra = sorted(set(attributes) - {"description", "description_status"})
        if extra:
            problems.append("%s: a meaning proposal carries only description and description_status, not %s" % (nid, ", ".join(extra)))
    if empty:
        problems.insert(0, "%d empty description(s)" % empty)
    return {"count": len(nodes), "problems": problems, "empty": empty}


def confirm(project, node_id, by, at, description=None, note=None):
    """A named person confirms a description: an assertion by them, the status moved, applied under
    the gates (decide.move, for a table's or column's description). Returns {"node", "label",
    "already", "assertion"?, "description"}."""
    from . import decide as _decide
    if not (by or "").strip():
        raise MeaningError("--by names the person who confirms: a decision has a name")
    if not at or not ISO_DATE.match(str(at)):
        raise MeaningError("--at YYYY-MM-DD is required: the date of the decision is never defaulted")
    live = _session.live(project)
    nodes = _index(live)
    node = nodes.get(node_id)
    if node is None:
        raise MeaningError("the graph holds no %s" % node_id)
    if node.get("type") not in (TABLE, COLUMN):
        raise MeaningError("%s is a %s, not a Table or a Column: only a meaning is confirmed here" % (node_id, node.get("type")))
    attributes = node.get("attributes") or {}
    current = (attributes.get("description") or "").strip()
    said = (description or "").strip() or None
    if said is None and not current:
        raise MeaningError("%s has no description to confirm: an agent drafts one (the data-meaning skill), or state it yourself with --description \"...\""
                           % node_id)
    final = said or current
    text = "%s confirmed the description of %s %s (%s): %s" % (by.strip(), node["type"].lower(), node.get("label") or node_id, node_id, final)
    if (note or "").strip():
        text += " [%s]" % note.strip()
    try:
        done = _decide.move(project, node_id, "description_status", CONFIRMED, by, at, note=note, also={"description": final},
                            action="data confirm", text=text)
    except _decide.DecideError as exc:
        raise MeaningError(str(exc))
    done["description"] = final
    return done
