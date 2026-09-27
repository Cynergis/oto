# -*- coding: utf-8 -*-
"""Stage 3 of 5. Generate the ontology in three forms from the declared vocabulary, cross-checked
against the node and relationship types actually used in the compiled graph.

Into `layout.ontology`:
  ontology.md              human-readable reference
  <slug>.ttl               Turtle (OWL/RDFS)
  <slug>.context.jsonld    JSON-LD context

The cross-check is the integrity gate. Every type and relation in the graph must be declared in
ontology.config.json, or the build reports it as unmapped. Optional sub-vocabularies declared in the
config (for example a power map) are rendered as extra sections.
"""

import os, json

from ..project import ProjectError


def run(project):
    _layout = project.layout
    ONT = _layout.ontology
    os.makedirs(ONT, exist_ok=True)
    identity = project.identity()
    SLUG = identity["slug"]
    BASE = identity["namespace"]
    PREFIX = identity["prefix"]

    graph = json.load(open(os.path.join(_layout.graph, "knowledge-graph.json"), encoding="utf-8"))

    # ---- Vocabulary ----
    # ontology.config.json is the ONLY source of this domain's vocabulary. There is no built-in
    # fallback on purpose: a missing or empty config must fail loudly, never silently emit another
    # project's classes and properties.
    _cfg_path = project.ontology_config_path
    if not os.path.exists(_cfg_path):
        raise ProjectError("ontology.config.json not found in %s. Declare your domain "
                           "vocabulary before building." % project.data)
    _cfg = json.load(open(_cfg_path, encoding="utf-8"))
    NAME = _cfg.get("name") or identity["name"]
    CLASSES = dict(_cfg.get("classes") or {})
    PROPS = {k: tuple(v) for k, v in (_cfg.get("properties") or {}).items()}
    TEMPORAL = {k: tuple(v) for k, v in (_cfg.get("temporal") or {}).items()}
    POWERMAP = dict(_cfg.get("powermap") or {})
    ATTRIBUTES = {k: dict(v or {}) for k, v in (_cfg.get("attributes") or {}).items()}
    XSD = {"string": "xsd:string", "number": "xsd:decimal", "integer": "xsd:integer",
           "boolean": "xsd:boolean", "date": "xsd:date", "list": "rdf:List"}

    def xsd_of(spec):
        return "xsd:string" if str(spec).startswith("enum:") else XSD.get(spec, "xsd:string")

    def attribute_meaning(spec, desc):
        return ("%s (one of: %s)" % (desc, spec[5:])) if str(spec).startswith("enum:") else desc
    if not CLASSES:
        raise ProjectError("ontology.config.json declares no classes.")
    if not PROPS:
        raise ProjectError("ontology.config.json declares no properties.")
    print(f"ontology: using project config {os.path.basename(_cfg_path)} "
          f"({len(CLASSES)} classes, {len(PROPS)} properties)")

    # sanity-check against graph
    graph_types = set(graph["meta"]["node_types"])
    graph_rels = set(graph["meta"]["relationship_types"])
    missing_cls = graph_types - set(CLASSES)
    missing_prop = graph_rels - set(PROPS)

    # ---------- ontology.md ----------
    md = [f"# {NAME} — Ontology\n",
          f"A lightweight domain ontology (OWL/RDFS-style) for the {NAME} knowledge system. "
          "It defines the **classes** (entity types) and **object properties** (relationship types) "
          "used across the knowledge graph (`graph/knowledge-graph.json` under the build directory).\n",
          f"- **Namespace:** `{BASE}` (prefix `{PREFIX}:`)",
          f"- **Classes:** {len(CLASSES)}  ·  **Object properties:** {len(PROPS)}  ·  "
          f"**Temporal/provenance properties:** {len(TEMPORAL)}",
          f"- **Validated against graph:** {len(graph_types)} node types, {len(graph_rels)} relationship types"
          + (f"  ⚠️ unmapped classes: {missing_cls}" if missing_cls else "")
          + (f"  ⚠️ unmapped props: {missing_prop}" if missing_prop else "  (all mapped ✓)"),
          "",
          "## Classes\n",
          "| Class | Description |", "| --- | --- |"]
    for c, d in CLASSES.items():
        md.append(f"| `{PREFIX}:{c}` | {d} |")
    md += ["", "## Object properties\n",
           "| Property | Domain | Range | Inverse | Meaning |", "| --- | --- | --- | --- | --- |"]
    for p, (dom, rng, inv, desc) in PROPS.items():
        md.append(f"| `{PREFIX}:{p}` | {dom} | {rng} | {('`'+inv+'`') if inv else '—'} | {desc} |")
    if ATTRIBUTES:
        md += ["", "## Attributes\n",
               "Typed values a node of the class may carry in its `attributes`. Absent is always allowed; "
               "a present value must fit the type. Exported as datatype properties.\n",
               "| Class | Attribute | Type | Meaning |", "| --- | --- | --- | --- |"]
        for c, attrs in ATTRIBUTES.items():
            for a, spec in attrs.items():
                md.append(f"| `{PREFIX}:{c}` | `{a}` | {spec[0]} | {spec[1] if len(spec) > 1 else ''} |")
    md += ["", "## Temporal & provenance vocabulary\n",
           "Optional annotation properties on **any** node or edge that capture *when* a fact was "
           "recorded, *when* it is valid, and *what it replaced* — so queries return the current "
           "state instead of stale answers while history stays auditable. Backward-compatible: an "
           "item without them is "
           "`status: current`.\n",
           "| Property | Kind | Meaning |", "| --- | --- | --- |"]
    for p, (kind, desc) in TEMPORAL.items():
        md.append(f"| `{PREFIX}:{p}` | {kind} | {desc} |")
    if POWERMAP:
        md += ["", "## Additional sub-vocabulary (`powermap`)\n",
               "Declared under `powermap` in the vocabulary config: an object a node may carry, with "
               "these fields.\n",
               "| Field | Definition |", "| --- | --- |"]
        for k, v in POWERMAP.items():
            md.append(f"| `{k}` | {v} |")
    md += ["", "## Design notes\n",
           "- The ontology is intentionally **lightweight** (RDFS/OWL-lite): named classes, typed object "
           "properties with domain/range and selected inverses. It is meant for navigation, validation and "
           "retrieval — not heavy reasoning.",
           "- **Instances** live in `graph/knowledge-graph.json` (nodes and edges) and `graph/triples.nt` "
           "(RDF), under the build directory.",
           "- Multi-valued domains/ranges are written `A|B` (union).",
           "- The same vocabulary backs the per-entity pages under `entities/` and the retrieval cards "
           "under `cards/`.",
           "- **`state` vs `status`:** a node may carry a domain-lifecycle `state` in its attributes "
           "(for example open, done, cancelled). That is the business state of the thing and is distinct "
           "from the node-level temporal **`status`** (current | superseded | proposed | intended) used for "
           "supersession. A done item is `state: done` while remaining `status: current`.", ""]
    open(os.path.join(ONT, "ontology.md"), "w", encoding="utf-8").write("\n".join(md))

    # ---------- <slug>.ttl ----------
    ttl = [f"@prefix {PREFIX}: <{BASE}> .",
           "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
           "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
           "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .", "",
           f"{PREFIX}: a owl:Ontology ; rdfs:label \"{NAME} Ontology\" .", ""]
    for c, d in CLASSES.items():
        ttl.append(f"{PREFIX}:{c} a owl:Class ; rdfs:label \"{c}\" ; rdfs:comment \"{d}\" .")
    ttl.append("")
    def rng_union(x): return ", ".join(f"{PREFIX}:{t}" for t in x.split("|"))
    for p, (dom, rng, inv, desc) in PROPS.items():
        # A null domain or range is "any class" and is simply not asserted.
        line = f"{PREFIX}:{p} a owl:ObjectProperty ; rdfs:label \"{p}\""
        if dom:
            line += f" ; rdfs:domain {rng_union(dom)}"
        if rng:
            line += f" ; rdfs:range {rng_union(rng)}"
        line += f" ; rdfs:comment \"{desc}\""
        if inv:
            line += f" ; owl:inverseOf {PREFIX}:{inv}"
        ttl.append(line + " .")
    if ATTRIBUTES:
        ttl.append("")
        ttl.append("# --- attributes: datatype properties per class ---")
        for c, attrs in ATTRIBUTES.items():
            for a, spec in attrs.items():
                desc = attribute_meaning(spec[0], spec[1] if len(spec) > 1 else "")
                ttl.append(f"{PREFIX}:{a} a owl:DatatypeProperty ; rdfs:label \"{a}\" ; rdfs:domain {PREFIX}:{c} ; "
                           f"rdfs:range {xsd_of(spec[0])} ; rdfs:comment \"{desc}\" .")
    ttl.append("")
    ttl.append("# --- temporal & provenance annotation properties ---")
    for p, (kind, desc) in TEMPORAL.items():
        ptype = "owl:ObjectProperty" if kind == "ref" else "owl:DatatypeProperty"
        rng = ("xsd:date" if kind == "date" else "xsd:string") if kind != "ref" else None
        line = f"{PREFIX}:{p} a {ptype} ; rdfs:label \"{p}\" ; rdfs:comment \"{desc}\""
        if rng:
            line += f" ; rdfs:range {rng}"
        if p == "supersedes":
            line += f" ; owl:inverseOf {PREFIX}:supersededBy"
        ttl.append(line + " .")
    ttl.insert(3, "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
    open(os.path.join(ONT, f"{SLUG}.ttl"), "w", encoding="utf-8").write("\n".join(ttl) + "\n")

    # ---------- JSON-LD context ----------
    ctx = {"@version": 1.1, PREFIX: BASE,
           "id": "@id", "type": "@type",
           "label": "rdfs:label", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}
    for p in PROPS:
        ctx[p] = {"@id": f"{PREFIX}:{p}", "@type": "@id"}
    for c, attrs in ATTRIBUTES.items():
        for a, spec in attrs.items():
            entry = {"@id": f"{PREFIX}:{a}"}
            if xsd_of(spec[0]) != "rdf:List":
                entry["@type"] = "http://www.w3.org/2001/XMLSchema#" + xsd_of(spec[0]).split(":")[1]
            ctx.setdefault(a, entry)
    for p, (kind, _desc) in TEMPORAL.items():
        if kind == "ref":
            ctx[p] = {"@id": f"{PREFIX}:{p}", "@type": "@id"}
        elif kind == "date":
            ctx[p] = {"@id": f"{PREFIX}:{p}", "@type": "http://www.w3.org/2001/XMLSchema#date"}
        else:
            ctx[p] = {"@id": f"{PREFIX}:{p}"}
    jsonld = {"@context": ctx,
              "classes": [f"{PREFIX}:{c}" for c in CLASSES],
              "properties": [f"{PREFIX}:{p}" for p in PROPS],
              "attributes": {c: list(attrs) for c, attrs in ATTRIBUTES.items()},
              "temporal_properties": [f"{PREFIX}:{p}" for p in TEMPORAL]}
    json.dump(jsonld, open(os.path.join(ONT, f"{SLUG}.context.jsonld"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"ontology: {len(CLASSES)} classes, {len(PROPS)} properties")
    print("unmapped classes:", missing_cls or "none", "| unmapped props:", missing_prop or "none")
