# -*- coding: utf-8 -*-
"""The graph as data: one payload a view's projection starts from.

`build(store)` reads the whole store through the same interface the twelve tools use, so the
payload holds nothing an agent could not be told, and a store that answers the equivalence battery
answers this the same way. JSON fields come back parsed; the shapes are the graph's own
(`from`/`rel`/`to` edges, attributes as objects), not the SQLite columns.

The same function feeds `/api/graph` on the HTTP front end and `build/site/data.json` in the
site stage, so live and static never disagree.
"""
import json
import os

PAYLOAD_VERSION = 1


def _loads(text, default):
    if text in (None, ""):
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _node(row, aliases):
    return {"id": row["id"], "type": row["type"], "label": row["label"], "status": row.get("status") or "current",
            "as_of": row.get("as_of"), "valid_from": row.get("valid_from"), "valid_to": row.get("valid_to"),
            "source_doc": row.get("source_doc"), "supersedes": _loads(row.get("supersedes"), None),
            "superseded_by": row.get("superseded_by"), "summary": row.get("summary") or "",
            "attributes": _loads(row.get("attributes"), {}), "tags": _loads(row.get("tags"), []),
            "sources": _loads(row.get("sources"), []), "aliases": list(aliases.get(row["id"]) or []),
            "degree": row.get("degree") or 0, "evidence": _loads(row.get("evidence"), [])}


def _edge(row):
    return {"from": row["src"], "rel": row["rel"], "to": row["dst"], "status": row.get("status") or "current",
            "derived_by": row.get("derived_by"), "premises": _loads(row.get("premises"), [])}


def vocabulary_for(project_root):
    """The declared vocabulary when the project's files are reachable, else None."""
    if not project_root:
        return None
    path = os.path.join(project_root, "ontology.config.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    return {"classes": config.get("classes") or {}, "properties": config.get("properties") or {},
            "attributes": config.get("attributes") or {}, "temporal": config.get("temporal") or {},
            "ontology_version": config.get("ontology_version")}


def derived_vocabulary(nodes, edges):
    """Classes and relations as the data uses them, for a store with no project beside it."""
    classes, properties = {}, {}
    for n in nodes:
        classes.setdefault(n["type"], {"definition": ""})
    for e in edges:
        properties.setdefault(e["rel"], {"definition": ""})
    return {"classes": classes, "properties": properties, "attributes": {}, "temporal": {}, "ontology_version": None,
            "derived_from_data": True}


def stations(project_root):
    """How many raw files wait at each station, when the project is reachable."""
    if not project_root:
        return None
    out = {}
    for name in ("inbox", "processing", "errors", "archive"):
        directory = os.path.join(project_root, name)
        count = 0
        if os.path.isdir(directory):
            for _root, _dirs, files in os.walk(directory):
                count += len([f for f in files if not f.startswith(".") and not f.endswith(".error.json")])
        out[name] = count
    return out


def pending_rows(project_root):
    """The pending lane's rows, when the project is reachable; [] otherwise."""
    if not project_root or not os.path.exists(os.path.join(project_root, "ontology.config.json")):
        return []
    from ..curate import pending as _pending
    try:
        collected = _pending.collect(project_root)
    except (OSError, ValueError):
        return []
    return [{k: v for k, v in row.items()} for row in collected["rows"]]


def change_token(build_seq, mode):
    """What the apps poll against: moves on a build and, in preview or watch mode, on a rebuild.
    Plain characters only, so it survives a query string unencoded."""
    stamp = (mode or {}).get("preview_built_at") or ""
    return "%s.%s" % (build_seq, "".join(ch for ch in str(stamp) if ch.isdigit()))


def build(store, project_root=None, identity=None, passages=True, ledger=50, mode=None):
    """Everything an app needs, from one store. `identity` is the project's config dict when known;
    `mode` says how the store is served (live, preview, watch) and what the preview rests on."""
    aliases = store.all_aliases()
    nodes = [_node(r, aliases) for r in store.all_nodes()]
    edges = [_edge(r) for r in store.all_edges()]
    derived = [{"node": r["node_id"], "name": r["name"], "value": _loads(r.get("value"), r.get("value")),
                "derived_by": r.get("derived_by"), "premises": _loads(r.get("premises"), [])}
               for r in store.all_derived_attributes()]
    findings = store.policy_findings(100000) or []
    lexicon = store.all_lexicon()
    changelog = store.changelog(ledger) or []
    for entry in changelog:
        entry["retired"] = _loads(entry.get("retired"), [])
        entry["sources"] = _loads(entry.get("sources"), [])
    counts = store.counts()
    counts["by_class"] = {r["type"]: r["c"] for r in store.types_current()}
    counts["by_relation"] = {r["rel"]: r["c"] for r in store.rels_counts(100000)}
    payload = {
        "payload_version": PAYLOAD_VERSION,
        "build_seq": store.meta("build_seq"),
        "schema_version": store.meta("schema_version"),
        "backend": store.kind,
        "project": {"slug": (identity or {}).get("slug"), "name": (identity or {}).get("name")},
        "vocabulary": vocabulary_for(project_root) or derived_vocabulary(nodes, edges),
        "counts": counts,
        "frontier": store.frontier(),
        "nodes": nodes,
        "edges": edges,
        "derived_attributes": derived,
        "findings": [{"rule": f["rule"], "severity": f["severity"], "node": f.get("node_id"), "message": f["message"]}
                     for f in findings],
        "lexicon": [dict(r) for r in lexicon],
        "documents": [{"id": d["id"], "label": d["label"], "as_of": d.get("as_of"), "valid_from": d.get("valid_from"),
                       "attributes": _loads(d.get("attributes"), {})} for d in store.documents(None, 100000)],
        "ledger": changelog,
        "stations": stations(project_root),
        "pending": pending_rows(project_root),
        "mode": dict(mode or {"regime": "live"}),
    }
    payload["token"] = change_token(payload["build_seq"], payload["mode"])
    if passages:
        payload["passages"] = [dict(r) for r in store.passages()]
    return payload


# ---- the rows behind one tool call, for a GET route ----

def tool_data(engine, name, args):
    """The structured counterpart of a tool's text, where the store has one. None otherwise."""
    store = engine.STORE
    if name in ("kg_entity", "kg_neighbors"):
        nid, alts = engine.resolve(args.get("term", ""))
        if not nid:
            return {"resolved": None, "alternatives": []}
        node = store.node(nid)
        return {"resolved": nid, "alternatives": alts, "node": _node(node, {nid: store.aliases(nid)}),
                "edges_out": [_edge(dict(e, src=nid)) for e in store.edges_out(nid, args.get("rel"))],
                "edges_in": [_edge(dict(e, dst=nid)) for e in store.edges_in(nid, args.get("rel"))],
                "derived_attributes": [dict(r, value=_loads(r.get("value"), None), premises=_loads(r.get("premises"), []))
                                       for r in store.derived_attributes(nid)],
                "predecessors": store.predecessors(nid)}
    if name == "kg_search":
        return {"rows": store.search(args.get("query", ""), int(args.get("n", 8)))}
    if name == "kg_by_type":
        return {"rows": store.by_type(args.get("type"), args.get("state"), int(args.get("limit", 50)))}
    if name == "kg_count":
        key = args.get("attr")
        return {"count": store.count(args.get("type"), args.get("tag"), key, args.get("value"))}
    if name == "kg_group_by":
        _key, _type, scheme, rows = engine.group_by_rows(args.get("by", ""), args.get("type"), args.get("tag"),
                                                         int(args.get("limit", 200)), args.get("level"))
        return {"rows": rows, "scheme": scheme}
    if name == "kg_stale":
        return {"status_counts": store.status_counts(), "superseded": store.superseded()}
    if name == "kg_policy":
        return {"rows": store.policy_findings(int(args.get("limit", 50))) or []}
    if name == "kg_overview":
        return {"counts": store.counts(), "by_class": store.types_current(), "by_relation": store.rels_counts(int(args.get("limit", 10))),
                "hubs": store.hubs(int(args.get("limit", 10))), "frontier": store.frontier(),
                "ledger": store.changelog(int(args.get("limit", 10))) or []}
    if name == "kg_actions":
        flag = lambda k: str(args.get(k, "")).lower() in ("1", "true", "yes", "on")   # noqa: E731
        return engine.actions_data(args.get("action"), args.get("on"), flag("ready"), flag("due"))
    if name == "kg_define":
        words = engine.vocabulary()
        return {"terms": [words.describe(kind, key) for kind, key in words.find(args.get("term", ""))]}
    if name == "kg_resolve":
        term = (args.get("term") or "").strip().lower()
        return {"lexicon": store.lexicon(term) or store.lexicon_fuzzy(term)}
    if name == "kg_docs":
        return {"rows": store.documents(args.get("query"), int(args.get("limit", 200))), "frontier": store.frontier()}
    if name == "kg_explain":
        nid, _alts = engine.resolve(args.get("term", ""))
        if not nid:
            return {"resolved": None}
        return {"resolved": nid,
                "derived_edges": [dict(r, premises=_loads(r.get("premises"), [])) for r in store.derived_edges(nid, args.get("rel"))],
                "derived_attributes": [dict(r, value=_loads(r.get("value"), None), premises=_loads(r.get("premises"), []))
                                       for r in store.derived_attributes(nid)]}
    return None
