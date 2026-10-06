# -*- coding: utf-8 -*-
"""Stage 1 of 5. Compile the curated graph (graph.json) into the knowledge layer.

Into `layout.graph`:
  knowledge-graph.json   full node+edge graph, with counts by type, relation and status
  entity-index.json      compact id -> {type, label, aliases, sources, degree, status}
  triples.nt             N-Triples: typed instances, their labels in every language, attributes
                         and temporal fields, under the IRIs the vocabulary declares
  graph.ttl              the same triples as prefixed Turtle, for people
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

    # ---- triples (N-Triples) ----
    # Instances live under the project's `id/` namespace and are typed with rdf:type; every class
    # and predicate is the IRI its ontology declares (model/namespaces.py), the same one the
    # ontology stage writes into `<slug>.ttl`, so the two files describe one graph.
    from ..model import vocabulary as _vocab
    from ..model.namespaces import Terms
    from . import rdf
    vocabulary = {}
    if os.path.exists(project.ontology_config_path):
        vocabulary = json.load(open(project.ontology_config_path, encoding="utf-8"))
    terms = Terms(vocabulary, identity)
    declared = vocabulary.get("attributes") or {}
    LANG = _vocab.languages(vocabulary)[0]
    # What else a node is called: the lexicon's phrases become alternative labels of their targets.
    spoken = {}
    lexicon_path = os.path.join(project.data, "lexicon.json")
    if os.path.exists(lexicon_path):
        for entry in json.load(open(lexicon_path, encoding="utf-8")).get("entries") or []:
            if entry.get("status", "current") != "current":
                continue
            for target in entry.get("targets") or []:
                spoken.setdefault(target, [])
                spoken[target] += [x for x in [entry.get("term")] + list(entry.get("aka") or []) if x]
    # temporal field -> term of the temporal vocabulary (camelCase, in the namespace it came from)
    TPRED = {"as_of": "asOf", "valid_from": "validFrom", "valid_to": "validTo",
             "status": "status", "supersedes": "supersedes",
             "superseded_by": "supersededBy", "source_doc": "sourceDoc"}
    DATES = ("as_of", "valid_from", "valid_to")
    lines, cells = [], [0]

    def triple(s, p, o):
        lines.append((s, p, o))

    def collection(items):
        """An ordered list as an RDF collection; its head, to use as an object."""
        head = "_:l%d" % (cells[0] + 1)
        for i, item in enumerate(items):
            cells[0] += 1
            triple("_:l%d" % cells[0], rdf.ref(rdf.RDF + "first"),
                   rdf.scalar(item) if rdf.is_scalar(item) else rdf.as_json(item))
            triple("_:l%d" % cells[0], rdf.ref(rdf.RDF + "rest"),
                   "_:l%d" % (cells[0] + 1) if i + 1 < len(items) else rdf.ref(rdf.RDF + "nil"))
        return head

    for nid, n in nodes.items():
        me = rdf.ref(terms.instance(nid))
        triple(me, rdf.ref(rdf.RDF + "type"), rdf.ref(terms.iri(n["type"])))
        triple(me, rdf.ref(rdf.RDFS + "label"), rdf.literal(n["label"]))
        # What the node is called: its label in the default language, its labels in the others,
        # its aliases and the lexicon's phrases as alternative labels, hidden labels for resolution only.
        triple(me, rdf.ref(rdf.SKOS + "prefLabel"), rdf.literal(n["label"], language=LANG))
        for lang, text in sorted(_vocab.texts(n.get("labels"), LANG).items()):
            if lang != LANG:
                triple(me, rdf.ref(rdf.SKOS + "prefLabel"), rdf.literal(text, language=lang))
        for alias in list(dict.fromkeys(list(n.get("aliases") or []) + spoken.get(nid, []))):
            if alias != n["label"]:
                triple(me, rdf.ref(rdf.SKOS + "altLabel"), rdf.literal(alias, language=LANG))
        for hidden in n.get("hidden_labels") or []:
            triple(me, rdf.ref(rdf.SKOS + "hiddenLabel"), rdf.literal(hidden))
        if n.get("summary"):
            triple(me, rdf.ref(rdf.RDFS + "comment"), rdf.literal(n["summary"], language=LANG))
        for k, pred in TPRED.items():
            if n.get(k) in (None, ""):
                continue
            if k in ("supersedes", "superseded_by"):  # object is an entity id (or list)
                for tgt in (n[k] if isinstance(n[k], list) else [n[k]]):
                    triple(me, rdf.ref(terms.temporal(pred)), rdf.ref(terms.instance(tgt)))
            else:
                triple(me, rdf.ref(terms.temporal(pred)), rdf.date(n[k]) if k in DATES else rdf.literal(n[k]))
        for key, value in (n.get("attributes") or {}).items():
            if value in (None, "", [], {}):
                continue
            spec = _vocab.declared_attributes(vocabulary, n["type"]).get(key)
            scheme = spec["type"][7:] if spec and str(spec["type"]).startswith("scheme:") else None
            if scheme and isinstance(value, str):             # a controlled value is its concept
                obj = rdf.ref(terms.iri("%s.%s" % (scheme, value), beside=scheme))
            elif rdf.is_scalar(value):
                obj = rdf.scalar(value, spec["type"] if spec else None)
            elif isinstance(value, list):
                obj = collection(value)
            else:
                obj = rdf.as_json(value)
            triple(me, rdf.ref(terms.iri(key)), obj)
    for e in edges:
        triple(rdf.ref(terms.instance(e["from"])), rdf.ref(terms.iri(e["rel"])), rdf.ref(terms.instance(e["to"])))
    with open(os.path.join(SEM, "triples.nt"), "w", encoding="utf-8") as f:
        f.writelines("%s %s %s .\n" % line for line in lines)
    with open(os.path.join(SEM, "graph.ttl"), "w", encoding="utf-8") as f:
        f.write(rdf.turtle(lines, dict(terms.prefixes, **{"id" if "id" not in terms.prefixes else "kg-id": terms.instances},
                                       rdf=rdf.RDF, rdfs=rdf.RDFS, skos=rdf.SKOS, xsd=rdf.XSD)))

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
