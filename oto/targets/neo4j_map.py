# -*- coding: utf-8 -*-
"""How an OTO graph is laid out in Neo4j. Pure functions: no driver, no network, sorted output.

    (:Entity:<Class> {key, id, project, label, summary, status, dates, sources, aliases, names, tags,
                      supersedes, superseded_by, degree, attributes_json,
                      <declared attributes, typed>, build_seq})
    (:Evidence {key, index, doc, where, quote})     <-[:EVIDENCED_BY]- entity
    (:Source {key, slug})                            <-[:CITES]- entity
    (:DerivedAttribute {key, name, value, derived_by, premises}) -[:DERIVED_ON]-> entity
    (:PolicyFinding {key, rule, severity, message}) -[:FLAGS]-> entity
    (a)-[:<relation> {kind: asserted|derived, status, derived_by, premises, build_seq}]->(b)
    (new)-[:SUPERSEDES]->(old)
    (:Passage {key, path, title, body})              the corpus, for passage search
    (:Lexicon {key, phrase, canonical, target, status, note})
    (:Changelog {key, at, by, note, nodes_added, nodes_changed, edges_added, retired, sources})
    (:OtoProject {key, slug, loads, build_seq, schema_version})

`key` is `<project>:<id>`: one uniqueness constraint on one property works in every edition, and
several projects can share one database. Declared attributes keep their types (a date is a date,
a number a number, a list a list); an undeclared attribute is stored as text, so the store never
guesses a type the vocabulary did not declare. `attributes_json` is the node's attributes exactly
as authored, which is what the query engine prints, so an answer from Neo4j reads like an answer
from SQLite. A source document is `:Source`, not `:Document`, because a vocabulary may declare a
class named Document. Everything carries `project` and `build_seq`, which is how a load retires
the previous build's facts once the new ones are in.
"""
import json
import re

LABEL_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
BASE_PROPS = ("id", "label", "summary", "status", "as_of", "valid_from", "valid_to", "source_doc",
              "source_type", "change_note")


def key(project, nid):
    return "%s:%s" % (project, nid)


def safe_name(name):
    """A label or relationship type Cypher can take without quoting tricks; refuses anything else."""
    if not LABEL_OK.match(name or ""):
        raise ValueError("cannot use %r as a Neo4j label or relationship type" % name)
    return name


def _typed(spec, value):
    """A declared attribute keeps its type. `date` values are marked so the loader can convert."""
    kind = (spec["type"] if spec else "string") or "string"
    if value is None:
        return None
    if kind.startswith("enum:") or kind == "string":
        return str(value)
    if kind == "number":
        if isinstance(value, bool):
            return str(value)
        return value if isinstance(value, int) else float(value)
    if kind == "integer":
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else str(value)
    if kind == "boolean":
        return bool(value)
    if kind == "list":
        return [str(x) for x in value] if isinstance(value, list) else [str(value)]
    if kind == "date":
        return {"__date__": str(value)}
    return str(value)


def plan(graph, config, project, build_seq, derived=None, passages=None, lexicon=None, changelog=None,
         schema_version=None, terms=None):
    """Everything the loader writes, as sorted lists of rows."""
    from . import rows as _rows
    from ..model import vocabulary as _vocab
    language = _vocab.languages(config)[0]
    classes = config.get("classes") or {}
    attributes = config.get("attributes") or {}
    derived = derived or {}
    nodes, evidence, documents, rels, derived_attrs, findings = [], [], {}, [], [], []

    degree = {}
    for edge in graph.get("edges") or []:
        degree[edge.get("from")] = degree.get(edge.get("from"), 0) + 1
        degree[edge.get("to")] = degree.get(edge.get("to"), 0) + 1

    for node in sorted(graph.get("nodes") or [], key=lambda n: n.get("id") or ""):
        nid = node.get("id")
        kind = node.get("type")
        if not nid or kind not in classes:
            continue
        props = {"key": key(project, nid), "id": nid, "project": project, "build_seq": build_seq,
                 "sources": list(node.get("sources") or []), "aliases": list(node.get("aliases") or []),
                 "names": [name for name, _kind, _lang in _rows.names_of(node, language)],
                 "aliases_text": " ".join(name for name, _kind, _lang in _rows.names_of(node, language)),
                 "tags": list(node.get("tags") or []),
                 "degree": degree.get(nid, 0),
                 "attributes_json": json.dumps(node.get("attributes") or {}, ensure_ascii=False)}
        for name in BASE_PROPS:
            if node.get(name) not in (None, ""):
                props[name] = node[name]
        props.setdefault("status", "current")
        if node.get("supersedes"):
            old = node["supersedes"]
            props["supersedes"] = [str(x) for x in old] if isinstance(old, list) else [str(old)]
        if node.get("superseded_by"):
            props["superseded_by"] = str(node["superseded_by"])
        declared = attributes.get(kind) or {}
        dates = []
        for name, value in sorted((node.get("attributes") or {}).items()):
            if name in props:
                continue
            spec = declared.get(name)
            typed = _typed(spec, value) if spec else (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            if isinstance(typed, dict) and "__date__" in typed:
                dates.append(name)
                typed = typed["__date__"]
            if typed is not None:
                props[name] = typed
        nodes.append({"label": safe_name(kind), "props": props, "dates": dates})
        for index, item in enumerate(node.get("evidence") or [], 1):
            if isinstance(item, dict) and item.get("doc"):
                evidence.append({"key": "%s:evidence:%d" % (key(project, nid), index), "entity": key(project, nid),
                                 "index": index, "doc": item.get("doc"), "where": item.get("where", ""), "quote": item.get("quote", ""),
                                 "project": project, "build_seq": build_seq})
        for slug in sorted(set((node.get("sources") or []) + ([node["source_doc"]] if node.get("source_doc") else []))):
            documents.setdefault(slug, {"key": "%s:document:%s" % (project, slug), "slug": slug,
                                        "project": project, "build_seq": build_seq})
            rels.append({"type": "CITES", "a": key(project, nid), "b": documents[slug]["key"],
                         "props": {"kind": "provenance", "build_seq": build_seq}})
        successor = node.get("superseded_by")
        if successor:
            rels.append({"type": "SUPERSEDES", "a": key(project, successor), "b": key(project, nid),
                         "props": {"kind": "temporal", "build_seq": build_seq}})

    known = {n["props"]["id"] for n in nodes}
    for edge in sorted(graph.get("edges") or [], key=lambda e: (e.get("from") or "", e.get("rel") or "", e.get("to") or "")):
        if edge.get("from") in known and edge.get("to") in known and edge.get("rel"):
            rels.append({"type": safe_name(edge["rel"]), "a": key(project, edge["from"]), "b": key(project, edge["to"]),
                         "props": {"kind": "asserted", "status": edge.get("status", "current"), "build_seq": build_seq}})
    for edge in sorted(derived.get("derived_edges") or [], key=lambda e: (e["from"], e["rel"], e["to"])):
        if edge["from"] in known and edge["to"] in known:
            rels.append({"type": safe_name(edge["rel"]), "a": key(project, edge["from"]), "b": key(project, edge["to"]),
                         "props": {"kind": "derived", "status": "derived", "derived_by": edge["derived_by"],
                                   "premises": list(edge.get("premises") or []), "build_seq": build_seq}})
    for item in sorted(derived.get("derived_attributes") or [], key=lambda a: (a["node"], a["name"])):
        if item["node"] in known:
            derived_attrs.append({"key": "%s:derived:%s" % (key(project, item["node"]), item["name"]),
                                  "entity": key(project, item["node"]), "name": item["name"],
                                  "value": json.dumps(item["value"], ensure_ascii=False), "derived_by": item["derived_by"],
                                  "premises": list(item.get("premises") or []), "project": project, "build_seq": build_seq})
    for index, item in enumerate(sorted(derived.get("findings") or [], key=lambda f: (f["rule"], str(f.get("node")))), 1):
        findings.append({"key": "%s:finding:%d" % (project, index), "rule": item["rule"], "severity": item["severity"],
                         "message": item["message"], "entity": key(project, item["node"]) if item.get("node") in known else None,
                         "project": project, "build_seq": build_seq})

    passage_rows = [dict(p, key="%s:passage:%s" % (project, p["path"]), project=project, build_seq=build_seq)
                    for p in sorted(passages or [], key=lambda p: p["path"])]
    lexicon_rows = [dict(r, key="%s:lexicon:%d" % (project, i), project=project, build_seq=build_seq)
                    for i, r in enumerate(lexicon or [], 1)]
    changelog_rows = [dict(r, key="%s:changelog:%d" % (project, i), project=project, build_seq=build_seq)
                      for i, r in enumerate(changelog or [], 1)]
    term_rows = [dict(r, key="%s:term:%s:%s" % (project, r["kind"], (r["owner"] + "." if r["owner"] else "") + r["name"]),
                      project=project, build_seq=build_seq) for r in terms or []]

    return {"project": project, "build_seq": build_seq, "schema_version": schema_version,
            "nodes": nodes, "evidence": evidence,
            "documents": [documents[k] for k in sorted(documents)], "rels": rels,
            "derived_attributes": derived_attrs, "findings": findings,
            "passages": passage_rows, "lexicon": lexicon_rows, "changelog": changelog_rows, "terms": term_rows,
            "labels": sorted({n["label"] for n in nodes}), "rel_types": sorted({r["type"] for r in rels})}


def summary(planned):
    return {"nodes": len(planned["nodes"]), "relationships": len(planned["rels"]),
            "evidence": len(planned["evidence"]), "documents": len(planned["documents"]),
            "derived_attributes": len(planned["derived_attributes"]), "findings": len(planned["findings"]),
            "passages": len(planned.get("passages") or [])}
