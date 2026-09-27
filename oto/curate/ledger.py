# -*- coding: utf-8 -*-
"""What the graph came to believe, and when, and why: one entry per apply, append-only.

The run manifests record which files came in. The previous-graph copy lets one apply be undone.
Neither answers, a year later, "why does the graph say this, and what did it say before". This
ledger does. Every `oto curate apply` appends what changed: the counts, each fact retired and the
note that says why, who applied it, and the note the applier left about what the change made
answerable and what it left open.

    changelog.jsonl     one JSON object per line, never rewritten
"""
import datetime
import json
import os

from .diff import index_nodes

NAME = "changelog.jsonl"


def path(project):
    return os.path.join(project.data, NAME)


def read(project):
    if not os.path.exists(path(project)):
        return []
    entries = []
    with open(path(project), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def retirements(live, candidate):
    """Facts the candidate marks superseded that the live graph did not, with the successor's note."""
    old, new = index_nodes(live), index_nodes(candidate)
    out = []
    for nid, node in new.items():
        if node.get("status") != "superseded":
            continue
        if (old.get(nid) or {}).get("status") == "superseded":
            continue
        successor = new.get(node.get("superseded_by") or "")
        out.append({"id": nid, "superseded_by": node.get("superseded_by"),
                    "valid_to": node.get("valid_to"),
                    "change_note": (successor or {}).get("change_note") or node.get("change_note")})
    return sorted(out, key=lambda r: r["id"])


def entry(summary, retired, by=None, note=None, runs=None, sources=None):
    return {"at": datetime.datetime.now().replace(microsecond=0).isoformat(),
            "by": by or "", "note": note or "",
            "runs": list(runs or []), "sources": sorted(sources or []),
            "nodes": {"added": len(summary["nodes_added"]), "removed": len(summary["nodes_removed"]),
                      "changed": len(summary["nodes_changed"]),
                      "reprovenanced": len(summary.get("nodes_reprovenanced") or [])},
            "edges": {"added": len(summary["edges_added"]), "removed": len(summary["edges_removed"])},
            "retired": retired}


def append(project, record):
    with open(path(project), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path(project)


def new_sources(live, candidate):
    """Source documents cited by the candidate that the live graph did not cite."""
    def cited(graph):
        out = set()
        for node in graph.get("nodes") or []:
            out.update(node.get("sources") or [])
            if node.get("source_doc"):
                out.add(node["source_doc"])
        return out
    return cited(candidate) - cited(live)


def render(entries, limit=20):
    lines = []
    for record in entries[-limit:]:
        n, e = record["nodes"], record["edges"]
        head = "%s  nodes +%d -%d ~%d  edges +%d -%d" % (record["at"], n["added"], n["removed"],
                                                          n["changed"], e["added"], e["removed"])
        if record.get("by"):
            head += "  by %s" % record["by"]
        lines.append(head)
        if record.get("sources"):
            lines.append("    from: %s" % ", ".join(record["sources"][:8]))
        for retired in record.get("retired") or []:
            lines.append("    retired %s -> %s%s" % (retired["id"], retired.get("superseded_by") or "?",
                                                    (": %s" % retired["change_note"]) if retired.get("change_note") else ""))
        if record.get("note"):
            lines.append("    %s" % record["note"])
    return "\n".join(lines) if lines else "no entries yet"
