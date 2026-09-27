# -*- coding: utf-8 -*-
"""Stage 4 of 5. Build the semantic retrieval layer from the compiled graph.

Into `layout.cards`:
  *.md                one self-contained, retrieval-optimised card per curated entity: YAML
                      frontmatter (id, type, aliases, tags, keywords, sources, temporal fields)
                      and a denormalised body that inlines neighbour context for recall
  index.json          manifest of the cards

Full-text search over the corpus, the notes, the entity pages and these cards lives in the SQLite
store's FTS5 table (stage 4). An inverted index used to be written here for a script that no
longer exists; nothing read it, so it is gone.
"""

import os, re, json
from collections import defaultdict


def run(project):
    _layout = project.layout
    SEM = _layout.graph
    CARDS = _layout.cards
    ENT_DIR = _layout.entities
    os.makedirs(SEM, exist_ok=True)
    os.makedirs(CARDS, exist_ok=True)

    graph = json.load(open(os.path.join(SEM, "knowledge-graph.json"), encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    out_edges = defaultdict(list); in_edges = defaultdict(list)
    for e in graph["edges"]:
        out_edges[e["from"]].append(e); in_edges[e["to"]].append(e)

    STOP = set("a an the of to in on for and or with by as at is are be this that these those it its "
               "from into within across each per via not no only e.g eg etc vs they their our we you "
               "will may can has have had who whom which what when where how all any both more most "
               "such than then there here over under between about above below up down out off then "
               "1 2 3 4 5 6 7 8 9 0".split())

    def tokenize(text):
        toks = re.findall(r"[A-Za-z][A-Za-z0-9&/+\-]{1,}", text.lower())
        return [t for t in toks if t not in STOP and len(t) > 1]

    # ---------- semantic documents (cards) ----------
    def card_keywords(n):
        kw = set(n.get("tags", []))
        kw.update(tokenize(n["label"]))
        for a in n.get("aliases", []):
            kw.update(tokenize(a))
        return sorted(kw)

    manifest = []
    curated = list(graph["nodes"])
    for n in curated:
        nid = n["id"]; slug = nid.replace(".", "__")
        related = []
        for e in out_edges.get(nid, []):
            t = nodes.get(e["to"]);
            if t: related.append(f"{e['rel']} → {t['label']}")
        for e in in_edges.get(nid, []):
            s = nodes.get(e["from"])
            if s: related.append(f"{s['label']} → {e['rel']}")
        kws = card_keywords(n)
        status = n.get("status", "current")
        fm = ["---", f"id: {nid}", f"type: {n['type']}", f"label: \"{n['label']}\"",
              f"aliases: {json.dumps(n.get('aliases', []), ensure_ascii=False)}",
              f"tags: {json.dumps(n.get('tags', []), ensure_ascii=False)}",
              f"keywords: {json.dumps(kws, ensure_ascii=False)}",
              f"status: {status}"]
        for k in ("as_of", "valid_from", "valid_to", "source_doc"):
            if n.get(k):
                fm.append(f"{k}: {n[k]}")
        if n.get("superseded_by"):
            fm.append(f"superseded_by: {n['superseded_by']}")
        fm += [f"sources: {json.dumps(n.get('sources', []), ensure_ascii=False)}",
               f"entity_page: {os.path.relpath(os.path.join(ENT_DIR, slug + '.md'), CARDS).replace(os.sep, '/')}",
               "---", ""]
        body = [f"# {n['label']}  ·  _{n['type']}_", ""]
        if status == "superseded":
            sb = n.get("superseded_by")
            sb_lbl = nodes[sb]["label"] if sb and sb in nodes else (sb or "a newer fact")
            body += [f"> ⚠️ SUPERSEDED as of {n.get('valid_to', '?')} — replaced by {sb_lbl}. "
                     "Do not retrieve as the current state.", ""]
        elif status == "proposed":
            body += ["> 🟡 PROPOSED — staged, not yet confirmed.", ""]
        elif status == "intended":
            body += ["> 🔵 INTENDED — asserted as a plan, not yet observed. Do not retrieve as the current state.", ""]
        body += [n.get("summary", ""), ""]
        attrs = n.get("attributes") or {}
        if attrs:
            body.append("**Key facts:** " + "; ".join(f"{k}={v}" for k, v in attrs.items() if v not in (None, "")) + ".")
            body.append("")
        if related:
            body.append("**Connected to:** " + "; ".join(related) + ".")
            body.append("")
        if n.get("sources"):
            body.append("**Sourced from:** " + ", ".join(n["sources"]) + ".")
        text = "\n".join(fm + body) + "\n"
        open(os.path.join(CARDS, slug + ".md"), "w", encoding="utf-8").write(text)
        manifest.append({"id": nid, "file": f"{slug}.md", "type": n["type"],
                         "label": n["label"], "status": status, "keywords": kws})
    json.dump({"count": len(manifest), "cards": manifest},
              open(os.path.join(CARDS, "index.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # self-cleaning: drop cards for entities that no longer exist, so the database does not index them
    _valid_cards = {n["id"].replace(".", "__") for n in curated}
    _pruned_cards = 0
    for _f in os.listdir(CARDS):
        if _f.endswith(".md") and _f[:-3] not in _valid_cards:
            os.remove(os.path.join(CARDS, _f)); _pruned_cards += 1

    print(f"semantic cards: {len(manifest)} (pruned {_pruned_cards} stale)")
