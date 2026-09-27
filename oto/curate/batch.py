# -*- coding: utf-8 -*-
"""Merge a batch of proposed facts into the candidate graph.

Authoring a graph from a corpus produces many small proposals: one file of nodes and edges per
source document, written by a person or by an agent that has read that document. Hand-editing a
growing candidate to add each one is where duplicate ids, lost sources and half-pasted JSON come
from. So a proposal is merged by rule instead:

  * a node whose id is new is added, with the routine fields defaulted (status, dates, sources);
  * a node whose id exists and whose facts agree gains the new sources and aliases, nothing else;
  * a node whose id exists and whose facts DIFFER is a conflict, and the batch is refused. A changed
    fact is a supersession, which needs a new id and a retirement of the old one, never a rewrite;
  * a node whose id exists and that carries only temporal fields (status, valid_to, superseded_by,
    change_note) is an update to those fields: the retirement half of a supersession;
  * an edge is added once, however many proposals repeat it;
  * `evidence` entries ({"doc", "where", "quote"}) accumulate: a fact seen in two places keeps both.

A node listed again by a proposal is RE-ATTESTED: its `as_of` moves to the proposal's date, because
the fact was observed again on that date. That is what lets a re-ingested document's facts be told
apart from the ones nobody has looked at since the old version.

A new node whose label or alias matches an existing node under a different id is reported as a
suspect. Near-duplicates are the most common way a graph quietly rots, and the two ids will not be
merged by anything downstream.

The batch is all or nothing. On any problem or conflict, nothing is written. Everything that is
written still goes through `oto curate check` before it can reach the live graph.

A proposal file:

    {"source_doc": "handbook",             optional: default source for every node in the file
     "as_of": "2026-03-01",                optional: default recording date (else today)
     "nodes": [{"id": "role.adjuster", "type": "Role", "label": "Claims adjuster", ...}],
     "edges": [{"from": "role.adjuster", "rel": "reports_to", "to": "role.manager"}]}
"""
import copy
import json

from .diff import FACTUAL_FIELDS, TEMPORAL_FIELDS, edge_key, index_nodes

REQUIRED_NEW_NODE = ("id", "type", "label")
REQUIRED_EDGE = ("from", "rel", "to")


def load(path):
    with open(path, encoding="utf-8") as f:
        proposal = json.load(f)
    if not isinstance(proposal, dict):
        raise ValueError("%s: a proposal is a JSON object with 'nodes' and/or 'edges'" % path)
    return proposal


def _names(node):
    out = {str(node.get("label") or "").strip().lower()}
    out.update(str(a).strip().lower() for a in (node.get("aliases") or []))
    out.discard("")
    return out


def _defaulted(raw, default_doc, default_as_of):
    node = dict(raw)
    node.setdefault("aliases", [])
    node.setdefault("tags", [])
    node.setdefault("attributes", {})
    node.setdefault("summary", "")
    node.setdefault("status", "current")
    node.setdefault("as_of", default_as_of)
    node.setdefault("valid_from", node["as_of"])
    if default_doc and not node.get("source_doc"):
        node["source_doc"] = default_doc
    if not node.get("sources"):
        node["sources"] = [node["source_doc"]] if node.get("source_doc") else []
    return node


def merge(candidate, proposal, today):
    """Return (merged graph, report). The graph passed in is not modified."""
    nodes = copy.deepcopy(candidate.get("nodes") or [])
    edges = copy.deepcopy(candidate.get("edges") or [])
    index = index_nodes({"nodes": nodes})
    seen_edges = {edge_key(e) for e in edges}
    names = {}
    for node in nodes:
        for name in _names(node):
            names.setdefault(name, node["id"])

    default_doc = proposal.get("source_doc")
    default_as_of = proposal.get("as_of") or today
    report = {"added": [], "merged": [], "updated": [], "conflicts": [], "suspects": [],
              "problems": [], "edges_added": 0, "edges_existing": 0, "edges_dangling": []}

    for raw in proposal.get("nodes") or []:
        nid = raw.get("id")
        if not nid:
            report["problems"].append("a node has no id: %s" % json.dumps(raw)[:80])
            continue
        existing = index.get(nid)

        if existing is None:
            missing = [k for k in REQUIRED_NEW_NODE if not raw.get(k)]
            if missing:
                report["problems"].append("new node %r lacks %s" % (nid, ", ".join(missing)))
                continue
            node = _defaulted(raw, default_doc, default_as_of)
            suspects = sorted({names[n] for n in _names(node) if n in names and names[n] != nid})
            if suspects:
                report["suspects"].append((nid, suspects))
            nodes.append(node)
            index[nid] = node
            for name in _names(node):
                names.setdefault(name, nid)
            report["added"].append(nid)
            continue

        changed = [f for f in FACTUAL_FIELDS if f != "attributes" and f in raw and raw[f] != existing.get(f)]
        new_attributes = {}
        if isinstance(raw.get("attributes"), dict):
            have = existing.get("attributes") or {}
            if any(k in have and have[k] != v for k, v in raw["attributes"].items()):
                changed.append("attributes")
            new_attributes = {k: v for k, v in raw["attributes"].items() if k not in have}
        if changed:
            report["conflicts"].append((nid, changed))
            continue
        if new_attributes:                                  # added, never overwritten: not a contradiction
            existing.setdefault("attributes", {}).update(new_attributes)
        temporal = [f for f in TEMPORAL_FIELDS if f in raw and raw[f] != existing.get(f)]
        for field in temporal:
            existing[field] = raw[field]
        new_sources = [s for s in (raw.get("sources") or ([default_doc] if default_doc else []))
                       if s not in (existing.get("sources") or [])]
        new_aliases = [a for a in (raw.get("aliases") or []) if a not in (existing.get("aliases") or [])]
        existing.setdefault("sources", []).extend(new_sources)
        existing.setdefault("aliases", []).extend(new_aliases)
        for item in raw.get("evidence") or []:
            if item not in (existing.get("evidence") or []):
                existing.setdefault("evidence", []).append(dict(item))
        if temporal or new_attributes:
            report["updated"].append((nid, temporal + (["attributes:" + ",".join(sorted(new_attributes))] if new_attributes else [])))
        else:
            if "as_of" not in raw and str(existing.get("as_of") or "") < str(default_as_of):
                existing["as_of"] = default_as_of           # observed again: re-attested
            report["merged"].append((nid, len(new_sources), len(new_aliases)))

    for raw in proposal.get("edges") or []:
        missing = [k for k in REQUIRED_EDGE if not raw.get(k)]
        if missing:
            report["problems"].append("edge %s lacks %s" % (json.dumps(raw)[:60], ", ".join(missing)))
            continue
        key = edge_key(raw)
        if key in seen_edges:
            report["edges_existing"] += 1
            continue
        edges.append(dict(raw))
        seen_edges.add(key)
        report["edges_added"] += 1
        for end in (raw["from"], raw["to"]):
            if end not in index:
                report["edges_dangling"].append("%s -%s-> %s" % key)

    out = dict(candidate)
    out["nodes"] = nodes
    out["edges"] = edges
    return out, report


def refused(report):
    """Why the batch must not be written, or an empty list."""
    reasons = list(report["problems"])
    for nid, fields in report["conflicts"]:
        reasons.append("%s: %s differ from the candidate. A changed fact is a supersession: give the "
                       "new fact a new id and retire the old one." % (nid, ", ".join(fields)))
    return reasons
