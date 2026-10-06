# -*- coding: utf-8 -*-
"""What both stores index besides the graph: the corpus passages, the lexicon, the recent ledger,
and the vocabulary's terms with their reasoning.

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


def names_of(node, default_language="en"):
    """Everything a node answers to besides its label: [(name, kind, language)] with kind `alias`
    (what it is also called), `label` (its label in another language) or `hidden` (a misspelling or
    a code, for resolution only, never shown)."""
    out = [(alias, "alias", default_language) for alias in node.get("aliases") or []]
    labels = node.get("labels") or {}
    out += [(text, "label", lang) for lang, text in labels.items() if isinstance(text, str) and text and lang != default_language]
    out += [(hidden, "hidden", default_language) for hidden in node.get("hidden_labels") or []]
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


def term_rows(project):
    """One row per term of the vocabulary, so a store answers what a class or a relation means
    without the project beside it: `name`, `kind` (class | relation | attribute | temporal | scheme),
    `owner` (the class, for an attribute; '' otherwise), `spec` and `rationale` as JSON text, `iri`."""
    from ..model import namespaces as _namespaces, rationale as _rationale
    path = project.ontology_config_path
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    record = _rationale.load(project)
    terms = _namespaces.Terms(config, project.identity())
    languages = config.get("languages") or []
    out = []

    def row(name, kind, owner, spec, why, iri):
        spec = dict(spec)
        if languages:
            spec["_languages"] = list(languages)
        out.append({"name": name, "kind": kind, "owner": owner, "spec": json.dumps(spec, ensure_ascii=False),
                    "rationale": json.dumps(why or {}, ensure_ascii=False), "iri": iri})

    for name, spec in (config.get("classes") or {}).items():
        row(name, "class", "", spec, (record.get("classes") or {}).get(name), terms.iri(name))
    for name, spec in (config.get("properties") or {}).items():
        row(name, "relation", "", spec, (record.get("properties") or {}).get(name), terms.iri(name))
    for owner, declared in (config.get("attributes") or {}).items():
        for name, spec in (declared or {}).items():
            row(name, "attribute", owner, spec, None, terms.iri(name))
    for name, spec in (config.get("temporal") or {}).items():
        row(name, "temporal", "", spec, None, terms.temporal(name))
    for name, spec in (config.get("schemes") or {}).items():
        row(name, "scheme", "", spec, None, terms.iri(name))
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
