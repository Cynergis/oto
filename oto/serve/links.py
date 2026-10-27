# -*- coding: utf-8 -*-
"""Cross-artifact navigation (roadmap D5): from any entity to the rules that apply to its class, the
terms and the words that name it, the graphs whose descriptor covers its class, the decisions about
it and the repository files behind it. Each link says where it lands (the rules page for a class,
the lexicon with a query, the dependencies page, an entity), so a reader walks from a thing to every
artifact that bears on it. Computed from the payload (serve/payload.py), so the same answer comes
from /api/links?entity=<id> and from the exported site; the workbench repeats it client-side
(ui-src/workbench/links.ts), and a test keeps the two in step.
"""
from ..model import vocabulary as _vocab

#: A decision is a thing of one of these classes, or of a kind of one.
DECISION_CLASSES = ("Decision", "DecisionRecord")
#: Files behind a thing: the class and what to show of it (an attribute, else the label).
FILE_CLASSES = {"Repository": ("repository", "url"), "CodeModule": ("code", "path"), "Commit": ("commit", "sha"), "Document": ("document", None)}


def _lineage(classes, name):
    return [name] + list(_vocab.ancestors(classes, name)) if name in classes else [name]


def _kind_of(classes, name, wanted):
    return next((w for w in _lineage(classes, name) if w in wanted), None)


def for_entity(payload, entity_id):
    """What bears on one entity, or None when the payload holds no such thing."""
    nodes = payload.get("nodes") or []
    by_id = {n["id"]: n for n in nodes}
    node = by_id.get(entity_id)
    if node is None:
        return None
    vocabulary = payload.get("vocabulary") or {}
    classes = vocabulary.get("classes") or {}
    kind = node.get("type")
    lineage = _lineage(classes, kind)

    rules_model = payload.get("rules") or {}
    rules = []
    wanted = set((rules_model.get("by_class") or {}).get(kind) or [])
    for r in rules_model.get("rules") or []:
        if r["id"] in wanted:
            via = None if kind in r["classes"] or r["every_node"] else next((a for a in lineage[1:] if a in r["classes"]), None)
            rules.append({"id": r["id"], "kind": r["kind"], "severity": r["severity"], "via": via, "target": {"section": "rules", "class": kind}})

    terms_model = payload.get("terms") or {}
    label = next((t["labels"].get(terms_model.get("default_language") or "en") for t in terms_model.get("terms") or []
                  if t["kind"] == "class" and t["name"] == kind), None)
    terms = [{"kind": "class", "name": kind, "label": label or _vocab.name_as_words(kind), "target": {"section": "ontology", "class": kind}}]
    for p in terms_model.get("phrases") or []:
        if p.get("target") == entity_id:
            terms.append({"kind": "phrase", "phrase": p["phrase"], "canonical": p["canonical"], "target": {"section": "lexicon", "query": p["phrase"]}})

    graphs = []
    for g in (payload.get("graphs") or {}).get("graphs") or []:
        if any(c in g["classes"] for c in lineage):
            graphs.append({"id": g["id"], "label": g["label"], "own": g["own"], "reach": g["reach"], "target": {"section": "dependencies", "graph": g["id"]}})

    decisions, files = [], []
    for e in payload.get("edges") or []:
        if (e.get("status") or "current") != "current":
            continue
        if e["from"] == entity_id:
            other, direction = by_id.get(e["to"]), "out"
        elif e["to"] == entity_id:
            other, direction = by_id.get(e["from"]), "in"
        else:
            continue
        if other is None or other["id"] == entity_id or (other.get("status") or "current") != "current":
            continue
        attrs = other.get("attributes") or {}
        if _kind_of(classes, other["type"], DECISION_CLASSES):
            decisions.append({"id": other["id"], "label": other.get("label"), "rel": e["rel"], "direction": direction,
                              "status": attrs.get("status"), "decided_on": attrs.get("decided_on"),
                              "target": {"section": "knowledge", "entity": other["id"]}})
        file_class = _kind_of(classes, other["type"], FILE_CLASSES)
        if file_class:
            file_kind, attribute = FILE_CLASSES[file_class]
            files.append({"id": other["id"], "label": other.get("label"), "kind": file_kind,
                          "where": (attrs.get(attribute) if attribute else None) or other.get("label"), "rel": e["rel"],
                          "target": {"section": "knowledge", "entity": other["id"]}})
    seen = {(f["id"], f["kind"]) for f in files}
    docs = []
    for ev in node.get("evidence") or []:
        if ev.get("doc") and ev["doc"] not in [d[0] for d in docs]:
            docs.append((ev["doc"], ev.get("where")))
    if node.get("source_doc") and node["source_doc"] not in [d[0] for d in docs]:
        docs.append((node["source_doc"], None))
    for doc, where in docs:
        document = by_id.get("document." + doc) or next((n for n in nodes if n.get("type") == "Document" and n.get("label") == doc), None)
        if document and (document["id"], "source") in seen:
            continue
        files.append({"id": document["id"] if document else None, "label": document.get("label") if document else doc, "kind": "source",
                      "where": doc + (" · " + where if where else ""), "rel": None,
                      "target": {"section": "knowledge", "entity": document["id"]} if document else None})
    return {"entity": entity_id, "type": kind, "rules": rules, "terms": terms, "graphs": graphs, "decisions": decisions, "files": files,
            "counts": {"rules": len(rules), "terms": len(terms), "graphs": len(graphs), "decisions": len(decisions), "files": len(files)}}
