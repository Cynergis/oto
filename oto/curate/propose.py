# -*- coding: utf-8 -*-
"""Proposals from a capture: what an elicitation tool collected, as facts for the gates.

A capture is what a tool wrote against a capture schema (compile/capture.py): items of a type,
each with a stable id, a label, fields and links, and where in the source it was said:

    {"doc": "fund-profile-prd", "as_of": "2026-10-07",
     "items": [{"type": "Requirement", "id": "FR3", "label": "Read every value from a finished column",
                "summary": "…", "fields": {"concerns": "data", "priority": "must"},
                "links": {"governs": ["report.fund-profile-balanced"]},
                "where": "§3.2", "quote": "The product reads finished columns; it never computes."}]}

`propose` checks it against the schema (an unknown type, field, link or choice is refused, named)
and writes an ordinary proposal: one node per item, id `<type>.<id>`, cited to the document with
the section and the quote as evidence; one edge per link, to another item of the capture by its
id or to a node of the graph by its node id. The proposal then goes through `oto curate add`
and `oto curate check` like any other: the tool contributes, the gates decide.
"""
import re

SLUG = re.compile(r"[^a-z0-9.-]+")


def node_id(kind, item_id, prefix=None):
    """`requirement.fr3`: the class as prefix, the capture's id as the local part, lowercase."""
    local = SLUG.sub("-", str(item_id).lower()).strip("-.")
    return "%s.%s" % (prefix or kind.lower(), local)


def problems(capture, schema):
    """What is wrong with a capture against its schema. Empty means it can be proposed."""
    out = []
    if not isinstance(capture, dict) or not isinstance(capture.get("items"), list):
        return ["a capture is {doc, as_of, items: [...]}"]
    if not (capture.get("doc") or "").strip():
        out.append("the capture names no `doc`: the document the items were captured from")
    types = schema.get("types") or {}
    ids = {}
    for number, item in enumerate(capture["items"], 1):
        label = "item %d" % number
        if not isinstance(item, dict):
            out.append("%s must be an object" % label)
            continue
        kind, item_id = item.get("type"), item.get("id")
        label = "item %s %s" % (kind or "?", item_id or "?")
        if kind not in types:
            out.append("%s: type %r is not in the capture schema (%s)" % (label, kind, ", ".join(sorted(types)) or "none"))
            continue
        if not item_id:
            out.append("%s: no id" % label)
            continue
        if not (item.get("label") or "").strip():
            out.append("%s: no label" % label)
        nid = node_id(kind, item_id, types[kind].get("id_prefix"))
        if nid in ids:
            out.append("%s: id %r is used twice" % (label, item_id))
        ids[nid] = kind
        fields = types[kind].get("fields") or {}
        for name, value in (item.get("fields") or {}).items():
            spec = fields.get(name)
            if spec is None:
                out.append("%s: %s captures no field %r (it has %s)" % (label, kind, name, ", ".join(sorted(fields)) or "none"))
            elif spec.get("choices") and value not in (None, "") and str(value) not in spec["choices"] \
                    and not (isinstance(value, list) and all(str(v) in spec["choices"] for v in value)):
                out.append("%s: %s is %r; the choices are %s" % (label, name, value, ", ".join(spec["choices"])))
        for name, spec in fields.items():
            if spec.get("required") and (item.get("fields") or {}).get(name) in (None, "", []):
                out.append("%s: %s is required and missing" % (label, name))
        links = types[kind].get("links") or {}
        for name, targets in (item.get("links") or {}).items():
            if name not in links:
                out.append("%s: %s has no link %r (it has %s)" % (label, kind, name, ", ".join(sorted(links)) or "none"))
            elif not isinstance(targets, list):
                out.append("%s: link %s must list its targets" % (label, name))
            elif links[name].get("max") is not None and len(targets) > links[name]["max"]:
                out.append("%s: link %s has %d targets; at most %d" % (label, name, len(targets), links[name]["max"]))
    return out


def propose(capture, schema, graph_ids=None):
    """The proposal: {source_doc, as_of, nodes, edges, unresolved}. A link target is an item of the
    capture (by its id, resolved to its node id) or a node of the graph (by its node id);
    anything else is listed under `unresolved` and left out."""
    types = schema.get("types") or {}
    doc, as_of = capture.get("doc"), capture.get("as_of")
    by_capture_id = {}
    for item in capture["items"]:
        kind = item["type"]
        by_capture_id[str(item["id"])] = node_id(kind, item["id"], types[kind].get("id_prefix"))
    graph_ids = set(graph_ids or [])
    nodes, edges, unresolved = [], [], []
    for item in capture["items"]:
        kind = item["type"]
        nid = by_capture_id[str(item["id"])]
        attributes = {k: v for k, v in (item.get("fields") or {}).items() if v not in (None, "", [])}
        node = {"id": nid, "type": kind, "label": item["label"].strip(), "aliases": list(item.get("aliases") or []),
                "summary": (item.get("summary") or item["label"]).strip(), "attributes": attributes, "tags": list(item.get("tags") or []),
                "source_doc": doc, "as_of": item.get("as_of") or as_of, "valid_from": item.get("valid_from") or item.get("as_of") or as_of,
                "status": "current", "sources": [doc],
                "evidence": [{"doc": doc, "where": item.get("where") or item["id"], "quote": item.get("quote") or item["label"]}]}
        nodes.append(node)
        for relation, targets in (item.get("links") or {}).items():
            for target in targets:
                if str(target) in by_capture_id:
                    edges.append({"from": nid, "rel": relation, "to": by_capture_id[str(target)]})
                elif str(target) in graph_ids or (graph_ids == set() and "." in str(target)):
                    edges.append({"from": nid, "rel": relation, "to": str(target)})
                else:
                    unresolved.append({"from": nid, "rel": relation, "to": str(target)})
    return {"source_doc": doc, "as_of": as_of, "nodes": nodes, "edges": edges, "unresolved": unresolved}
