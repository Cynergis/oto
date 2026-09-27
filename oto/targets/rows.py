# -*- coding: utf-8 -*-
"""What both stores index besides the graph: the corpus passages, the lexicon, the recent ledger.

One walk, one row shape, so the SQLite target and the Neo4j target cannot drift apart on what a
passage or a lexicon row is. The serving stores are compared query for query in a test; that test
only holds if the two targets were fed the same rows.
"""
import json
import os

LEDGER_TAIL = 50


def passages(layout):
    """Every Markdown file under the indexed directories: `path` (the layout's label), `title`, `body`."""
    out = []
    for directory in layout.indexed:
        for root, _dirs, files in os.walk(directory):
            if os.sep + "assets" in root:
                continue
            for name in sorted(files):
                if not name.endswith(".md"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name)
                out.append({"path": layout.label(path), "title": title, "body": text})
    return out


def lexicon_rows(project):
    """One row per (phrase, target): `phrase` lowercased, `canonical`, `target` ('' when none), `status`, `note`."""
    path = os.path.join(project.data, "lexicon.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        entries = json.load(f).get("entries", [])
    out = []
    for entry in entries:
        phrases = [entry["term"]] + (entry.get("aka") or [])
        targets = entry.get("targets") or [""]          # [""] => one row, no entity (e.g. not_ingested)
        status, note = entry.get("status", "current"), entry.get("note", "")
        for phrase in phrases:
            for target in targets:
                out.append({"phrase": phrase.strip().lower(), "canonical": entry["term"], "target": target,
                            "status": status, "note": note})
    return out


def changelog_rows(project, tail=LEDGER_TAIL):
    """The last `tail` ledger entries, flattened; `retired` and `sources` as JSON text."""
    from ..curate import ledger as _ledger
    out = []
    for record in _ledger.read(project)[-tail:]:
        nodes, edges = record.get("nodes") or {}, record.get("edges") or {}
        out.append({"at": record.get("at"), "by": record.get("by"), "note": record.get("note"),
                    "nodes_added": nodes.get("added", 0), "nodes_changed": nodes.get("changed", 0),
                    "edges_added": edges.get("added", 0),
                    "retired": json.dumps(record.get("retired") or [], ensure_ascii=False),
                    "sources": json.dumps(record.get("sources") or [], ensure_ascii=False)})
    return out
