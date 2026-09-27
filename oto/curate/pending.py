# -*- coding: utf-8 -*-
"""What is on its way into the graph, labelled by station.

A fact captured but not yet believed sits somewhere on disk: a file in `inbox/` nobody has read,
a document in `processing/` extracted and not yet drafted, a proposal under `proposals/` drafted
from one document, or the candidate `graph.candidate.json` under check. This module reads those
places and returns the pending facts in one shape, each with its `station`, so a view can show
them beside the believed graph without ever mixing the two, and a tool can list them.

Proposals are merged the way `oto curate add --dry-run` merges them, on top of the candidate when
one is open and the live graph otherwise, in file order, so what the lane shows is what `add`
would do. A proposal that would be refused is still listed, with the reason: nothing enters
quietly and nothing vanishes quietly.

    {"stations": {"inbox": 2, "processing": 1, "errors": 0, "archive": 7, "proposals": 3, "candidate": true},
     "counts": {"proposal": 12, "candidate": 3, "refused": 1},
     "rows": [{"kind": "node", "station": "candidate", "verdict": "new", "source": "candidate",
               "id": "...", "type": "...", "label": "...", ...},
              {"kind": "edge", "station": "proposal", "verdict": "new", "source": "proposals/memo.json",
               "from": "...", "rel": "...", "to": "..."},
              {"kind": "node", "station": "proposal", "verdict": "refused", "reason": "...", ...}]}
"""
import copy
import datetime
import json
import os

from . import batch as _batch
from .diff import FACTUAL_FIELDS, TEMPORAL_FIELDS, edge_key

CANDIDATE_NAME = "graph.candidate.json"
PROPOSALS_DIR = "proposals"
NODE_FIELDS = ("id", "type", "label", "summary", "status", "as_of", "valid_from", "valid_to", "source_doc",
               "supersedes", "superseded_by", "change_note", "attributes", "tags", "aliases", "sources", "evidence")
STATIONS = ("inbox", "processing", "proposal", "candidate", "live")


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _graph_path(root):
    return os.path.join(root, "graph.json")


def _node_row(node, station, verdict, source, reason=None):
    row = {"kind": "node", "station": station, "verdict": verdict, "source": source, "reason": reason}
    for key in NODE_FIELDS:
        if key in node:
            row[key] = copy.deepcopy(node[key])
    row.setdefault("attributes", {}); row.setdefault("tags", []); row.setdefault("aliases", [])
    row.setdefault("sources", []); row.setdefault("evidence", []); row.setdefault("status", "current")
    return row


def _edge_row(edge, station, verdict, source):
    return {"kind": "edge", "station": station, "verdict": verdict, "source": source,
            "from": edge.get("from"), "rel": edge.get("rel"), "to": edge.get("to")}


def _file_count(directory):
    if not os.path.isdir(directory):
        return 0
    n = 0
    for _root, _dirs, files in os.walk(directory):
        n += len([f for f in files if not f.startswith(".") and not f.endswith(".error.json") and not f.endswith(".lock")])
    return n


def candidate_rows(live, candidate):
    """What the candidate changes against the live graph."""
    rows = []
    live_nodes = {n["id"]: n for n in live.get("nodes") or [] if n.get("id")}
    for node in candidate.get("nodes") or []:
        nid = node.get("id")
        if not nid:
            continue
        old = live_nodes.get(nid)
        if old is None:
            rows.append(_node_row(node, "candidate", "new", "candidate"))
            continue
        factual = [f for f in FACTUAL_FIELDS if node.get(f) != old.get(f)]
        temporal = [f for f in TEMPORAL_FIELDS if node.get(f) != old.get(f)]
        if node.get("status") == "superseded" and old.get("status") != "superseded":
            rows.append(_node_row(node, "candidate", "retire", "candidate"))
        elif factual:
            rows.append(_node_row(node, "candidate", "changed", "candidate", "changed: " + ", ".join(factual)))
        elif temporal:
            rows.append(_node_row(node, "candidate", "updated", "candidate", "updated: " + ", ".join(temporal)))
    live_edges = {edge_key(e) for e in live.get("edges") or []}
    for edge in candidate.get("edges") or []:
        if edge_key(edge) not in live_edges:
            rows.append(_edge_row(edge, "candidate", "new", "candidate"))
    return rows


def proposal_rows(base, root, today=None):
    """What every proposal would add on top of `base`, in file order, refusals included."""
    today = today or datetime.date.today().isoformat()
    directory = os.path.join(root, PROPOSALS_DIR)
    if not os.path.isdir(directory):
        return [], base, []
    rows, files = [], sorted(f for f in os.listdir(directory) if f.endswith(".json") and not f.startswith("."))
    graph = base
    for name in files:
        source = "%s/%s" % (PROPOSALS_DIR, name)
        try:
            proposal = _batch.load(os.path.join(directory, name))
        except (OSError, ValueError) as exc:
            rows.append({"kind": "file", "station": "proposal", "verdict": "refused", "source": source,
                         "reason": "cannot read: %s" % exc})
            continue
        before_ids = {n["id"] for n in graph.get("nodes") or [] if n.get("id")}
        before_edges = {edge_key(e) for e in graph.get("edges") or []}
        merged, report = _batch.merge(graph, proposal, today)
        refusals = _batch.refused(report)
        by_id = {n["id"]: n for n in merged.get("nodes") or [] if n.get("id")}
        if refusals:
            # the batch as a whole would be refused: list what it carries, each marked refused
            for raw in proposal.get("nodes") or []:
                if raw.get("id"):
                    rows.append(_node_row(raw, "proposal", "refused", source, "; ".join(refusals)[:300]))
            for raw in proposal.get("edges") or []:
                row = _edge_row(raw, "proposal", "refused", source); row["reason"] = "; ".join(refusals)[:300]
                rows.append(row)
            continue
        for nid in report["added"]:
            rows.append(_node_row(by_id[nid], "proposal", "new", source))
        for nid, fields in report["updated"]:
            rows.append(_node_row(by_id[nid], "proposal", "retire" if by_id[nid].get("status") == "superseded" else "updated",
                                  source, "updated: " + ", ".join(fields)))
        for nid, suspects in report["suspects"]:
            for row in rows:
                if row.get("id") == nid and row["station"] == "proposal":
                    row["reason"] = "same name as %s: one entity or two?" % ", ".join(suspects)
        for edge in merged.get("edges") or []:
            if edge_key(edge) not in before_edges:
                rows.append(_edge_row(edge, "proposal", "new", source))
        for dangling in report["edges_dangling"]:
            for row in rows:
                if row["kind"] == "edge" and "%s -%s-> %s" % (row["from"], row["rel"], row["to"]) == dangling:
                    row["reason"] = "points at a node not in the graph yet"
        graph = merged
        del before_ids
    return rows, graph, files


def collect(root, today=None):
    """Everything pending in the project at `root`, and the graph it would produce."""
    live = _read(_graph_path(root), {"nodes": [], "edges": []})
    candidate_path = os.path.join(root, CANDIDATE_NAME)
    has_candidate = os.path.exists(candidate_path)
    candidate = _read(candidate_path, live) if has_candidate else live
    rows = candidate_rows(live, candidate) if has_candidate else []
    proposal, composed, files = proposal_rows(candidate, root, today)
    rows += proposal
    counts = {"candidate": 0, "proposal": 0, "refused": 0}
    for row in rows:
        if row["verdict"] == "refused":
            counts["refused"] += 1
        else:
            counts[row["station"]] += 1
    stations = {name: _file_count(os.path.join(root, name)) for name in ("inbox", "processing", "errors", "archive")}
    stations["proposals"] = len(files)
    stations["candidate"] = has_candidate
    return {"stations": stations, "counts": counts, "rows": rows, "composed": composed,
            "differs": len([r for r in rows if r["verdict"] != "refused"])}


def text(pending, limit=40):
    """The pending lane as text, for the tool and the CLI."""
    st, counts = pending["stations"], pending["counts"]
    lines = ["Pending, by station:",
             "  inbox        %d file(s) not yet read" % st.get("inbox", 0),
             "  processing   %d document(s) extracted, not yet drafted" % st.get("processing", 0),
             "  proposals    %d file(s): %d fact(s) would be added%s" % (st.get("proposals", 0), counts["proposal"],
                                                                        (", %d refused" % counts["refused"]) if counts["refused"] else ""),
             "  candidate    %s" % (("open: %d change(s) against the live graph" % counts["candidate"]) if st.get("candidate") else "none open")]
    rows = pending["rows"]
    if not rows:
        lines.append("Nothing is pending: what the graph believes is all there is.")
        return "\n".join(lines)
    lines.append("")
    for station in ("candidate", "proposal"):
        mine = [r for r in rows if r["station"] == station]
        if not mine:
            continue
        lines.append("%s (%d):" % (station, len(mine)))
        for r in mine[:limit]:
            if r["kind"] == "edge":
                what = "%s -%s-> %s" % (r["from"], r["rel"], r["to"])
            elif r["kind"] == "file":
                what = r["source"]
            else:
                what = "%s (%s) %s" % (r.get("label", "?"), r.get("type", "?"), r.get("id", ""))
            reason = ("  [%s]" % r["reason"]) if r.get("reason") else ""
            lines.append("  %-8s %s  <- %s%s" % (r["verdict"], what, r["source"], reason))
        if len(mine) > limit:
            lines.append("  ... %d more" % (len(mine) - limit))
    lines.append("")
    lines.append("A pending fact is not believed. `oto curate check` then `oto curate apply` moves it; `oto preview` "
                 "builds a store that includes all of it.")
    return "\n".join(lines)
