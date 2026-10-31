# -*- coding: utf-8 -*-
"""The architecture pack's served tool (ADR-0011): `arch_context`, what an agent must know before it edits
(roadmap H3), answered from the served graph. The engine mounts it through the pack's `provides.tools`
(oto/extensions.py) when the served project composes the architecture pack, serves it at
/api/arch-context, and forwards it across graphs like its own tools. It reads the store through the
engine's serve module, which holds the open store and the matching the kg_* tools use."""
import json

from oto.serve import engine as _E


def _attrs(n):
    try:
        return json.loads(n["attributes"] or "{}") if n else {}
    except (TypeError, ValueError):
        return {}


def _module_for_path(path):
    """The code module whose path is the longest prefix of `path`, or None."""
    wanted = path.strip().replace("\\", "/")
    while wanted.startswith("./"):
        wanted = wanted[2:]
    wanted = wanted.strip("/")
    best = None
    for row in _E.STORE.by_type("CodeModule", limit=100000):
        module_path = (_attrs(_E.node(row["id"])).get("path") or "").strip("/")
        if module_path and (wanted == module_path or wanted.startswith(module_path + "/")):
            if best is None or len(module_path) > len(best[1]):
                best = (row["id"], module_path)
    return best


def arch_context_text(path=None, node_term=None):
    """What an agent must know before it edits: the node (by id or name, or the component that
    implements a path of the code), the requirements it satisfies with each budget and the latest
    measured value, the decisions that govern it, the controls on it and on its connections, its
    connections, the modules that implement it with their last commit, and the open change proposals
    about it (roadmap H3)."""
    if not (path or "").strip() and not (node_term or "").strip():
        raise ValueError("arch_context takes a path (a file or directory of the code) or a node (an id or a name of the architecture)")
    module = None
    if (path or "").strip():
        found = _module_for_path(path)
        if not found:
            raise ValueError("no code module of the architecture covers %r: map the repository first (oto arch map), or the path is untraced code" % path)
        module = found[0]
        owners = [e["src"] for e in _E.STORE.edges_in(module, "implemented_by")]
        if not owners:
            mn = _E.node(module)
            return "=== %s  [CodeModule]  (%s) ===\nfrom %s\nno component of the architecture implements it: untraced code (AR9). Map it to its component in oto.codemap.json, or record the component first." % (mn["label"], module, path)
        nid = owners[0]
    else:
        m = _E.match(node_term)
        if not m["id"]:
            return _E.no_match(node_term, m)
        nid = m["id"]
    n = _E.node(nid)
    a = _attrs(n)
    L = ["=== %s  [%s]  (%s) ===" % (n["label"], n["type"], nid)]
    if n["summary"]:
        L.append(n["summary"])
    if a.get("external_type") or a.get("external_id"):
        L.append("framework node: %s (%s)" % (a.get("external_id") or "-", a.get("external_type") or "-"))
    if module:
        L.append("from %s (%s)" % (path, _E.label(module)))
    reqs = [e["dst"] for e in _E.STORE.edges_out(nid, "satisfies") if _E.node(e["dst"])]
    L.append("requirements:" if reqs else "requirements: none recorded")
    for r in reqs:
        rn = _E.node(r)
        ra = _attrs(rn)
        line = "  %s" % rn["label"]
        if ra.get("metric"):
            line += ": %s" % ra["metric"]
            parts = []
            if ra.get("budget"):
                parts.append("budget %s" % ra["budget"])
            evidence = sorted((_E.node(e["src"]) for e in _E.STORE.edges_in(r, "measurement_of") if _E.node(e["src"])),
                              key=lambda x: _attrs(x).get("observed_on") or "", reverse=True)
            if evidence:
                ea = _attrs(evidence[0])
                parts.append("measured %s on %s" % (ea.get("value") or "?", ea.get("observed_on") or "?"))
            if parts:
                line += " (%s)" % ", ".join(parts)
        L.append(line)
    decisions = []
    for rel in ("governs", "about"):
        for e in _E.STORE.edges_in(nid, rel):
            dn = _E.node(e["src"])
            if dn and dn["type"] == "Decision" and e["src"] not in decisions:
                decisions.append(e["src"])
    L.append("decisions:" if decisions else "decisions: none recorded")
    for d in decisions:
        dn = _E.node(d)
        da = _attrs(dn)
        line = "  %s [%s]" % (dn["label"], da.get("status") or dn["status"])
        if dn["status"] == "superseded" and dn["superseded_by"]:
            line += " superseded by %s" % _E.label(dn["superseded_by"])
        if da.get("rationale"):
            line += ": %s" % da["rationale"]
        L.append(line)
    relationships = [(e["src"], "from") for e in _E.STORE.edges_in(nid, "connects_from") if _E.node(e["src"])]
    relationships += [(e["src"], "to") for e in _E.STORE.edges_in(nid, "connects_to") if _E.node(e["src"])]
    controls = [(e["src"], None) for e in _E.STORE.edges_in(nid, "safeguards") if _E.node(e["src"])]
    for rid, _d in relationships:
        controls += [(e["src"], rid) for e in _E.STORE.edges_in(rid, "safeguards") if _E.node(e["src"])]
    L.append("controls:" if controls else "controls: none")
    for c, rid in controls:
        cn = _E.node(c)
        ca = _attrs(cn)
        L.append("  %s%s%s" % (cn["label"], " on %s" % _E.label(rid) if rid else "", " (%s)" % ca["requirement_url"] if ca.get("requirement_url") else ""))
    L.append("connections:" if relationships else "connections: none")
    for rid, d in relationships:
        rn = _E.node(rid)
        ra = _attrs(rn)
        other_rel = "connects_to" if d == "from" else "connects_from"
        others = [e["dst"] for e in _E.STORE.edges_out(rid, other_rel) if e["dst"] != nid]
        L.append("  %s %s (%s%s)" % ("→" if d == "from" else "←", ", ".join(_E.label(o) for o in others) or rn["label"],
                                      ra.get("kind") or "?", ", %s" % ra["protocol"] if ra.get("protocol") else ""))
    modules = [e["dst"] for e in _E.STORE.edges_out(nid, "implemented_by") if _E.node(e["dst"]) and _E.node(e["dst"])["type"] == "CodeModule"]
    L.append("modules:" if modules else "modules: none mapped")
    for mid in modules:
        mn = _E.node(mid)
        ma = _attrs(mn)
        commits = sorted((_E.node(e["src"]) for e in _E.STORE.edges_in(mid, "touches") if _E.node(e["src"])), key=lambda c: _attrs(c).get("committed_on") or "", reverse=True)
        line = "  %s%s" % (ma.get("path") or mn["label"], " (%s)" % ma["language"] if ma.get("language") else "")
        if commits:
            ca = _attrs(commits[0])
            line += ", last touched %s on %s by %s" % ((ca.get("sha") or "")[:7], ca.get("committed_on") or "?", ca.get("author") or "?")
        L.append(line)
    proposals = [e["src"] for e in _E.STORE.edges_in(nid, "proposes_change_to") if _E.node(e["src"]) and (_attrs(_E.node(e["src"])).get("status") or "proposed") == "proposed"]
    if proposals:
        L.append("open change proposals:")
        L += ["  %s" % _E.label(p) for p in proposals]
    return "\n".join(L)


#: What the engine mounts beside its kg_* tools: the same shape as its own entries, with the GET route
#: it answers at and whether a dependency's graph may be asked for it (kg_call).
TOOLS = [
    {"name": "arch_context",
     "description": "What an agent must know before it edits: for a path of the code or a node of the architecture, the node, "
                    "the requirements it satisfies with each budget and the latest measured value, the decisions that govern it, "
                    "the controls on it and on its connections, its connections, the modules that implement it with their last "
                    "commit, and the open change proposals about it. The architecture pack's graph answers; a path resolves "
                    "through the code map (oto arch map).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "a file or directory of the code, relative to its repository"},
         "node": {"type": "string", "description": "a node of the architecture: an id or a name"}}},
     "fn": lambda a: arch_context_text(a.get("path"), a.get("node")),
     "route": "arch-context", "forwardable": True},
]
