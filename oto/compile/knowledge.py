# -*- coding: utf-8 -*-
"""Stage 1 of 5. Compile the curated graph (graph.json) into the knowledge layer.

Into `layout.graph`:
  knowledge-graph.json   full node+edge graph, with counts by type, relation and status
  entity-index.json      compact id -> {type, label, aliases, sources, degree, status}
  triples.nt             N-Triples (subject predicate object), temporal fields included
  entities.csv           node table
  relationships.csv      edge table
Into `layout.entities`:
  *.md                   one page per curated entity, with backlinks
"""

import os, json, csv, re


def run(project):
    _layout = project.layout
    SEM = _layout.graph
    ENT_DIR = _layout.entities
    os.makedirs(SEM, exist_ok=True)
    os.makedirs(ENT_DIR, exist_ok=True)

    identity = project.identity()
    BASE = identity["namespace"]

    domain = json.load(open(project.graph_path, encoding="utf-8"))

    nodes = {n["id"]: dict(n) for n in domain["nodes"]}
    edges = list(domain["edges"])
    # The actions the project declares (actions/*.json) are facts too: each becomes an Action
    # node whose source is its file. They are never written into graph.json.
    from ..actions import model as _actions
    action_nodes, action_edges = _actions.nodes_and_edges(_actions.load(project))
    for n in action_nodes:
        if n["id"] not in nodes:
            nodes[n["id"]] = n
    from ..actions import runs as _runs
    for action_id, last in _runs.last_runs(project).items():
        if action_id in nodes:
            nodes[action_id]["attributes"]["last_run"] = {k: last.get(k) for k in ("at", "on", "by", "stamp", "ready", "recorded_at")}
            nodes[action_id]["attributes"]["runs"] = last["runs"]
    action_edges += _runs.acts_on_edges(project)
    known = {(e["from"], e["rel"], e["to"]) for e in edges}
    edges += [e for e in action_edges if (e["from"], e["rel"], e["to"]) not in known and e["from"] in nodes and e["to"] in nodes]

    # ---- temporal / provenance helpers (see TEMPORAL_SCHEMA.md; all fields optional) ----
    TEMPORAL_FIELDS = ("as_of", "valid_from", "valid_to", "status",
                       "supersedes", "superseded_by", "source_doc", "change_note")

    def temporal(n):
        """Return only the temporal fields present on a node/edge, status-defaulted."""
        t = {k: n[k] for k in TEMPORAL_FIELDS if k in n and n[k] not in (None, "")}
        if "status" not in t and any(k in n for k in TEMPORAL_FIELDS):
            t["status"] = "current"
        return t

    def status_of(n):
        return n.get("status", "current")

    # ---- degree ----
    degree = {nid: 0 for nid in nodes}
    for e in edges:
        if e["from"] in degree: degree[e["from"]] += 1
        if e["to"] in degree: degree[e["to"]] += 1

    # ---- write knowledge-graph.json ----
    os.makedirs(SEM, exist_ok=True)
    graph = {
        "meta": {"name": f"{identity['name']} Knowledge Graph", "base": BASE,
                 "node_count": len(nodes), "edge_count": len(edges),
                 "node_types": sorted({n["type"] for n in nodes.values()}),
                 "relationship_types": sorted({e["rel"] for e in edges}),
                 "status_counts": {s: sum(1 for n in nodes.values() if status_of(n) == s)
                                   for s in ("current", "superseded", "proposed", "intended")
                                   if sum(1 for n in nodes.values() if status_of(n) == s)}},
        "nodes": list(nodes.values()),
        "edges": edges,
    }
    json.dump(graph, open(os.path.join(SEM, "knowledge-graph.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # ---- entity-index.json (compact, retrieval-friendly) ----
    index = {}
    for nid, n in nodes.items():
        index[nid] = {"type": n["type"], "label": n["label"],
                      "aliases": n.get("aliases", []),
                      "tags": n.get("tags", []),
                      "sources": n.get("sources", []),
                      "degree": degree.get(nid, 0),
                      "status": status_of(n)}
        if n.get("as_of"):
            index[nid]["as_of"] = n["as_of"]
    json.dump(index, open(os.path.join(SEM, "entity-index.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # ---- triples (N-Triples-ish) ----
    def uri(x): return f"<{BASE}{x}>"
    # temporal field -> RDF predicate (camelCase under the opt: namespace)
    TPRED = {"as_of": "asOf", "valid_from": "validFrom", "valid_to": "validTo",
             "status": "status", "supersedes": "supersedes",
             "superseded_by": "supersededBy", "source_doc": "sourceDoc"}
    def esc(s): return str(s).replace("\\", "\\\\").replace('"', '\\"')
    with open(os.path.join(SEM, "triples.nt"), "w", encoding="utf-8") as f:
        for nid, n in nodes.items():
            f.write(f'{uri(nid)} <{BASE}rel/type> "{n["type"]}" .\n')
            lbl = n["label"].replace('"', '\\"')
            f.write(f'{uri(nid)} <http://www.w3.org/2000/01/rdf-schema#label> "{lbl}" .\n')
            for k, pred in TPRED.items():
                if n.get(k) in (None, ""):
                    continue
                if k in ("supersedes", "superseded_by"):  # object is an entity id (or list)
                    for tgt in (n[k] if isinstance(n[k], list) else [n[k]]):
                        f.write(f'{uri(nid)} <{BASE}rel/{pred}> {uri(tgt)} .\n')
                else:
                    f.write(f'{uri(nid)} <{BASE}rel/{pred}> "{esc(n[k])}" .\n')
        for e in edges:
            f.write(f'{uri(e["from"])} <{BASE}rel/{e["rel"]}> {uri(e["to"])} .\n')

    # ---- CSV node / edge tables ----
    with open(os.path.join(SEM, "entities.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "type", "label", "tags", "degree", "sources",
                                       "status", "as_of", "valid_from", "valid_to", "supersedes"])
        for nid, n in nodes.items():
            sup = n.get("supersedes", "")
            if isinstance(sup, list):
                sup = "|".join(sup)
            w.writerow([nid, n["type"], n["label"], "|".join(n.get("tags", [])),
                        degree.get(nid, 0), "|".join(n.get("sources", [])),
                        status_of(n), n.get("as_of", ""), n.get("valid_from", ""),
                        n.get("valid_to", ""), sup])
    with open(os.path.join(SEM, "relationships.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["from", "rel", "to"])
        for e in edges:
            w.writerow([e["from"], e["rel"], e["to"]])

    # ---- per-entity KB pages for curated entities ----
    out_edges = {}
    in_edges = {}
    for e in edges:
        out_edges.setdefault(e["from"], []).append(e)
        in_edges.setdefault(e["to"], []).append(e)

    def slug_for(nid): return nid.replace(".", "__")

    curated = list(nodes.values())
    for n in curated:
        nid = n["id"]
        lines = [f"---",
                 f"id: {nid}",
                 f"type: {n['type']}",
                 f"label: \"{n['label']}\"",
                 f"aliases: {json.dumps(n.get('aliases', []), ensure_ascii=False)}",
                 f"tags: {json.dumps(n.get('tags', []), ensure_ascii=False)}",
                 f"sources: {json.dumps(n.get('sources', []), ensure_ascii=False)}",
                 f"---", "",
                 f"# {n['label']}", "",
                 f"**Type:** {n['type']}  ·  **ID:** `{nid}`", ""]
        if status_of(n) == "superseded":
            sb = n.get("superseded_by")
            link = f"[{nodes[sb]['label']}](./{slug_for(sb)}.md)" if sb and sb in nodes else (sb or "a newer fact")
            lines += [f"> ⚠️ **SUPERSEDED** as of {n.get('valid_to', '?')} — replaced by {link}. "
                      "Kept for history; do not cite as current.", ""]
        elif status_of(n) == "proposed":
            lines += ["> 🟡 **PROPOSED** — staged, not yet confirmed.", ""]
        elif status_of(n) == "intended":
            lines += ["> 🔵 **INTENDED** — asserted as a plan, not yet observed. Do not cite as the current state.", ""]
        if n.get("aliases"):
            lines.append(f"**Also known as:** {', '.join(n['aliases'])}")
            lines.append("")
        lines.append(n.get("summary", ""))
        lines.append("")
        attrs = n.get("attributes") or {}
        if attrs:
            lines.append("## Attributes")
            lines.append("")
            for k, v in attrs.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")
        oe = out_edges.get(nid, [])
        if oe:
            lines.append("## Relationships (outgoing)")
            lines.append("")
            for e in oe:
                tgt = nodes.get(e["to"])
                tlabel = tgt["label"] if tgt else e["to"]
                if tgt:
                    lines.append(f"- {e['rel']} → [{tlabel}](./{slug_for(e['to'])}.md)")
                else:  # a target outside the graph has no page; render plain
                    lines.append(f"- {e['rel']} → {tlabel}")
            lines.append("")
        ie = list(in_edges.get(nid, []))
        if ie:
            lines.append("## Relationships (incoming)")
            lines.append("")
            for e in ie:
                src = nodes.get(e["from"])
                slabel = src["label"] if src else e["from"]
                lines.append(f"- [{slabel}](./{slug_for(e['from'])}.md) → {e['rel']}")
            lines.append("")
        tinfo = temporal(n)
        if tinfo:
            lines.append("## Provenance & validity")
            lines.append("")
            order = ["status", "as_of", "valid_from", "valid_to",
                     "supersedes", "superseded_by", "source_doc", "change_note"]
            for k in order:
                if k not in tinfo:
                    continue
                v = tinfo[k]
                if k in ("supersedes", "superseded_by"):
                    ids = v if isinstance(v, list) else [v]
                    v = ", ".join(f"[{nodes[i]['label']}](./{slug_for(i)}.md)" if i in nodes else i
                                  for i in ids)
                lines.append(f"- **{k}:** {v}")
            lines.append("")
        if n.get("sources"):
            lines.append("## Sources")
            lines.append("")
            for s in n["sources"]:
                lines.append(f"- {s}")
            lines.append("")
        if n.get("evidence"):
            lines.append("## Evidence")
            lines.append("")
            for item in n["evidence"]:
                where = f" {item['where']}" if item.get("where") else ""
                quote = f': "{item["quote"]}"' if item.get("quote") else ""
                lines.append(f"- {item.get('doc', '?')}{where}{quote}")
            lines.append("")
        open(os.path.join(ENT_DIR, slug_for(nid) + ".md"), "w", encoding="utf-8").write("\n".join(lines))

    # self-cleaning: drop pages for entities that no longer exist in the graph (no manual prune needed)
    _valid_pages = {slug_for(n["id"]) for n in curated}
    _pruned = 0
    for _f in os.listdir(ENT_DIR):
        if _f.endswith(".md") and _f[:-3] not in _valid_pages:
            os.remove(os.path.join(ENT_DIR, _f)); _pruned += 1

    print(f"nodes={len(nodes)} edges={len(edges)} curated_pages={len(curated)} pruned_pages={_pruned}")
    print("knowledge layer written to %s and %s" % (os.path.basename(SEM), os.path.basename(ENT_DIR)))
