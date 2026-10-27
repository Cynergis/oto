# -*- coding: utf-8 -*-
"""The graph descriptors as a person reads them (roadmap D4): this graph and the graphs it depends on,
who depends on whom, and the pairs an agent could not tell apart, each flagged with the words that
set them apart (oto/graphs.py measures that; this projects it). Carried in the graph payload as
`graphs` (so an exported site has it) and served at /api/graphs (`?graph=<id>` for one).

A graph entry: id, label, subject, classes, reach, slug, own (this project's descriptor), depends_on
and depended_on_by (ids), near_duplicates ([{other, similarity, same_reach, told_apart: {this, other},
message}]). `own` is graph.<slug>, else the descriptor whose slug is the project's, else the one graph
nothing depends on; None when nobody is. `pairs` is the lint's own finding list.
"""
from .. import graphs as _graphs


def _attrs(node):
    a = node.get("attributes")
    return a if isinstance(a, dict) else {}


def _own(rows, edges, slug):
    for n in rows:
        if slug and (n["id"] == _graphs.node_id(slug) or _attrs(n).get("slug") == slug):
            return n["id"]
    depended = {e["to"] for e in edges}
    roots = [n["id"] for n in rows if n["id"] not in depended]
    return roots[0] if len(roots) == 1 else None


def model(nodes, edges, slug=None):
    """The descriptors projected, this graph first."""
    rows = sorted((n for n in nodes or [] if n.get("type") == _graphs.CLASS and (n.get("status") or "current") == "current"),
                  key=lambda n: n.get("id") or "")
    ids = {n["id"] for n in rows}
    links = [e for e in edges or [] if e.get("rel") == _graphs.DEPENDS_ON and (e.get("status") or "current") == "current"
             and e.get("from") in ids and e.get("to") in ids]
    own = _own(rows, links, slug)
    pairs = _graphs.overlaps(rows)
    out = []
    for n in rows:
        a = _attrs(n)
        near = []
        for p in pairs:
            if n["id"] == p["a"]:
                near.append({"other": p["b"], "similarity": p["similarity"], "same_reach": p["same_reach"],
                             "told_apart": {"this": p["only_a"], "other": p["only_b"]}, "message": p["message"]})
            elif n["id"] == p["b"]:
                near.append({"other": p["a"], "similarity": p["similarity"], "same_reach": p["same_reach"],
                             "told_apart": {"this": p["only_b"], "other": p["only_a"]}, "message": p["message"]})
        out.append({"id": n["id"], "label": n.get("label"), "subject": a.get("subject"), "classes": list(a.get("classes") or []),
                    "reach": a.get("reach"), "slug": a.get("slug"), "own": n["id"] == own,
                    "depends_on": sorted(e["to"] for e in links if e["from"] == n["id"]),
                    "depended_on_by": sorted(e["from"] for e in links if e["to"] == n["id"]),
                    "near_duplicates": near})
    out.sort(key=lambda g: (not g["own"], g["id"]))
    return {"own": own, "counts": {"graphs": len(out), "dependencies": len(links), "near_duplicates": len(pairs)}, "graphs": out, "pairs": pairs}


def for_graph(m, graph_id):
    """One descriptor, or None."""
    return next((g for g in (m or {}).get("graphs") or [] if g["id"] == graph_id), None)
