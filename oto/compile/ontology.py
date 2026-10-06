# -*- coding: utf-8 -*-
"""Stage 3 of 5. Generate the ontology in three forms from the declared vocabulary, cross-checked
against the node and relationship types actually used in the compiled graph.

Into `layout.ontology`:
  ontology.md              human-readable reference (terms, hierarchy, shapes, questions)
  questions.yaml           the competency questions rendered as SPARQL over graph.ttl
  <slug>.ttl               Turtle (OWL/RDFS)
  <slug>.context.jsonld    JSON-LD context

Every term is written under the IRI its ontology declares (model/namespaces.py), the same IRI the
knowledge stage uses in `triples.nt`, so the ontology describes the exported graph.

The cross-check is the integrity gate. Every type and relation in the graph must be declared in
ontology.config.json, or the build reports it as unmapped. Optional sub-vocabularies declared in the
config (for example a power map) are rendered as extra sections.
"""

import os, json, re

from ..model import rationale as _rationale, vocabulary as _vocab
from ..model.namespaces import Terms
from ..project import ProjectError
from . import rdf


def _vocab_cardinality(spec):
    """`at least 1`, `at most 1`, `exactly 1`, `between 1 and 3`."""
    low, high = spec.get("min") or 0, spec.get("max")
    if high is None:
        return "at least %d" % low
    if not low:
        return "at most %d" % high
    if low == high:
        return "exactly %d" % low
    return "between %d and %d" % (low, high)


def run(project):
    _layout = project.layout
    ONT = _layout.ontology
    os.makedirs(ONT, exist_ok=True)
    identity = project.identity()
    SLUG = identity["slug"]
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
    PROPS = dict(_cfg.get("properties") or {})
    TEMPORAL = dict(_cfg.get("temporal") or {})
    POWERMAP = dict(_cfg.get("powermap") or {})
    ATTRIBUTES = {k: dict(v or {}) for k, v in (_cfg.get("attributes") or {}).items()}
    LANG = _vocab.languages(_cfg)[0]
    terms = Terms(_cfg, identity)
    WHY = _rationale.load(project)
    # An attribute name is one property, whichever classes declare it: name -> [(class, spec)].
    ATTRIBUTE_HOLDERS = {}
    for _c, _attrs in ATTRIBUTES.items():
        for _a, _spec in _attrs.items():
            ATTRIBUTE_HOLDERS.setdefault(_a, []).append((_c, _spec))
    XSD = {"string": "xsd:string", "number": "xsd:decimal", "integer": "xsd:integer",
           "boolean": "xsd:boolean", "date": "xsd:date", "list": "rdf:List"}

    SCHEMES = dict(_cfg.get("schemes") or {})

    def xsd_of(spec):
        return "xsd:string" if str(spec).startswith("enum:") else XSD.get(spec, "xsd:string")

    def scheme_of(spec):
        return spec[7:] if str(spec).startswith("scheme:") else None

    def concept(scheme, key):
        return terms.curie("%s.%s" % (scheme, key), beside=scheme)

    def meaning(spec):
        """An attribute's definition per language, the enum's values or the scheme spelled out."""
        out = _vocab.texts(spec.get("definition"), LANG)
        if str(spec.get("type", "")).startswith("enum:"):
            out = {lang: "%s (one of: %s)" % (d, spec["type"][5:]) for lang, d in out.items()} or \
                  {LANG: "(one of: %s)" % spec["type"][5:]}
        elif scheme_of(spec.get("type")):
            out = {lang: "%s (a concept of %s)" % (d, scheme_of(spec["type"])) for lang, d in out.items()} or \
                  {LANG: "(a concept of %s)" % scheme_of(spec["type"])}
        return out

    def label_of(spec, name):
        return _vocab.texts(spec.get("label"), LANG) or {LANG: _vocab.name_as_words(name)}

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
    def one(texts):
        return texts.get(LANG) or next(iter(texts.values()), "")

    def why_cells(section, name):
        entry = (WHY.get(section) or {}).get(name) or {}
        return (entry.get("why") or "").strip(), (entry.get("validated_by") or "").strip() or "—"

    md = [f"# {NAME} — Ontology\n",
          f"A lightweight domain ontology (OWL/RDFS-style) for the {NAME} knowledge system. "
          "It defines the **classes** (entity types) and **object properties** (relationship types) "
          "used across the knowledge graph (`graph/knowledge-graph.json` under the build directory).\n",
          "- **Terms:** " + ", ".join(f"`{prefix}:` <{iri}>" + (" (this project's own)" if prefix == PREFIX else "")
                                     for prefix, iri in terms.prefixes.items()),
          f"- **Instances:** <{terms.instances}>",
          "- **Languages:** " + ", ".join(_vocab.languages(_cfg)),
          f"- **Classes:** {len(CLASSES)}  ·  **Object properties:** {len(PROPS)}  ·  "
          f"**Temporal/provenance properties:** {len(TEMPORAL)}",
          f"- **Validated against graph:** {len(graph_types)} node types, {len(graph_rels)} relationship types"
          + (f"  ⚠️ unmapped classes: {missing_cls}" if missing_cls else "")
          + (f"  ⚠️ unmapped props: {missing_prop}" if missing_prop else "  (all mapped ✓)"),
          "",
          "## Classes\n",
          "| Class | Label | A kind of | Definition | Why it exists | Confirmed by |", "| --- | --- | --- | --- | --- | --- |"]
    for c, spec in CLASSES.items():
        why, by = why_cells("classes", c)
        kind_of = ", ".join(f"`{p}`" for p in spec.get("subclass_of") or []) or "—"
        md.append(f"| `{terms.curie(c)}` | {one(label_of(spec, c))} | {kind_of} | {one(_vocab.texts(spec.get('definition'), LANG))} | {why} | {by} |")
    tree = _vocab.covers(CLASSES)
    roots = [c for c in CLASSES if not (CLASSES[c].get("subclass_of"))]
    if any(len(tree[c]) > 1 for c in CLASSES):
        md += ["", "The hierarchy, as a question about a class covers the kinds of it:", ""]

        def branch(kind, depth):
            md.append("%s- `%s`" % ("  " * depth, kind))
            for child in CLASSES:
                if kind in (CLASSES[child].get("subclass_of") or []):
                    branch(child, depth + 1)
        for root in roots:
            branch(root, 0)
    md += ["", "## Object properties\n",
           "| Property | Label | Domain | Range | Inverse | Specialises | Definition |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for p, spec in PROPS.items():
        inv = spec.get("inverse")
        inverse = f"`{inv}` ({one(_vocab.texts(spec.get('inverse_label'), LANG) or {LANG: _vocab.name_as_words(inv)})})" if inv else "—"
        md.append(f"| `{terms.curie(p)}` | {one(label_of(spec, p))} | {spec.get('domain') or 'any'} | {spec.get('range') or 'any'} | "
                  f"{inverse} | {('`' + spec['subproperty_of'] + '`') if spec.get('subproperty_of') else '—'} | "
                  f"{one(_vocab.texts(spec.get('definition'), LANG))} |")
    if ATTRIBUTES:
        md += ["", "## Attributes\n",
               "Typed values a node of the class may carry in its `attributes`. Absent is always allowed; "
               "a present value must fit the type. Exported as datatype properties.\n",
               "| Class | Attribute | Label | Type | Definition |", "| --- | --- | --- | --- | --- |"]
        for c, attrs in ATTRIBUTES.items():
            for a, spec in attrs.items():
                typed = f"`{spec['type']}`" if scheme_of(spec["type"]) else spec["type"]
                md.append(f"| `{terms.curie(c)}` | `{a}` | {one(label_of(spec, a))} | {typed} | "
                          f"{one(_vocab.texts(spec.get('definition'), LANG))} |")
    if SCHEMES:
        md += ["", "## Controlled values\n",
               "A scheme's concepts are the values an attribute of type `scheme:<Name>` may take, each with its "
               "label and definition; a concept narrower than another rolls up to it (`kg_group_by ... level=top`).\n"]
        for name, scheme in SCHEMES.items():
            md += [f"### `{terms.curie(name)}` — {one(label_of(scheme, name))}", "",
                   one(_vocab.texts(scheme.get("definition"), LANG)), "",
                   "| Concept | Label | Narrower than | Definition |", "| --- | --- | --- | --- |"]
            for key, c in (scheme.get("concepts") or {}).items():
                md.append(f"| `{key}` | {one(label_of(c, key))} | {('`' + c['broader'] + '`') if c.get('broader') else '—'} | "
                          f"{one(_vocab.texts(c.get('definition'), LANG))} |")
    from ..reason import shapes as _shapes, questions as _questions
    declared_shapes = _shapes.declared(_cfg)
    if declared_shapes:
        md += ["", "## Shapes\n",
               "The constraints the graph is held to. `oto curate check` refuses a candidate that breaks one; "
               "the Turtle carries them as SHACL.\n",
               "| Class | Constraint | On | Says |", "| --- | --- | --- | --- |"]
        for row in declared_shapes:
            if row["kind"] == "min":
                says = "at least %d" % row["count"]
            elif row["kind"] == "max":
                says = "at most %d" % row["count"]
            elif row["kind"] == "required":
                says = "every instance carries a value"
            else:
                says = "every instance carries it"
            md.append(f"| `{row['class'] or 'any'}` | {row['kind']} | `{row['subject']}` | {says} |")
    QUESTIONS = _questions.load(project)
    if QUESTIONS:
        md += ["", "## Competency questions\n",
               "What the vocabulary exists to answer. Each runs over the graph (`kg_ask`, `oto query ask`); "
               "`questions.yaml` beside this file holds the SPARQL rendering of each.\n",
               "| Id | Who asks | Question | Gate | Covers | Confirmed by |", "| --- | --- | --- | --- | --- | --- |"]
        cited = _questions.terms_cited(QUESTIONS, _cfg)
        for qid, q in QUESTIONS.items():
            covers_terms = sorted(t for t, ids in cited.items() if qid in ids)
            md.append(f"| {qid} | {q.get('who') or 'anyone'} | {q.get('question', '')} | {q.get('gate', 'non_empty')} | "
                      f"{', '.join('`%s`' % t for t in covers_terms)} | {q.get('validated_by') or '—'} |")
    md += ["", "## Temporal & provenance vocabulary\n",
           "Optional annotation properties on **any** node or edge that capture *when* a fact was "
           "recorded, *when* it is valid, and *what it replaced* — so queries return the current "
           "state instead of stale answers while history stays auditable. An item without them is "
           "`status: current`.\n",
           "| Property | Label | Kind | Definition |", "| --- | --- | --- | --- |"]
    for t, spec in TEMPORAL.items():
        md.append(f"| `{terms.temporal_curie(t)}` | {one(label_of(spec, t))} | {spec['type']} | {one(_vocab.texts(spec.get('definition'), LANG))} |")
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
           "- Multi-valued domains/ranges are written `A|B` (union); the Turtle writes them as `owl:unionOf`.",
           "- Every term carries its labels (`skos:prefLabel`), definition (`skos:definition`) and, when "
           "recorded, the reasoning behind it (`meta:question`, `meta:rationale`, `meta:alternatives`, "
           "`meta:validatedBy`) in the Turtle.",
           "- The same vocabulary backs the per-entity pages under `entities/` and the retrieval cards "
           "under `cards/`.",
           "- **`state` vs `status`:** a node may carry a domain-lifecycle `state` in its attributes "
           "(for example open, done, cancelled). That is the business state of the thing and is distinct "
           "from the node-level temporal **`status`** (current | superseded | proposed | intended) used for "
           "supersession. A done item is `state: done` while remaining `status: current`.", ""]
    open(os.path.join(ONT, "ontology.md"), "w", encoding="utf-8").write("\n".join(md))

    # ---------- <slug>.ttl ----------
    def q(text, lang=None):
        return '"%s"' % rdf.escape(text) + (f"@{lang}" if lang else "")

    def tagged(predicate, texts):
        """`pred "a"@en , "b"@fr`, or nothing when there is no text."""
        return f" ; {predicate} " + " , ".join(q(t, lang) for lang, t in texts.items()) if texts else ""

    def labels(spec, name):
        """rdfs:label and skos:prefLabel per language, skos:altLabel for the alternatives."""
        pref = label_of(spec, name)
        return tagged("rdfs:label", pref) + tagged("skos:prefLabel", pref) + tagged(
            "skos:altLabel", {}) + "".join(f" ; skos:altLabel " + " , ".join(q(x, lang) for x in items)
                                             for lang, items in _vocab.alt_labels(spec.get("alt_labels"), LANG).items())

    def notes(spec, definitions=None):
        """rdfs:comment and skos:definition from the definition, then scope note and example."""
        texts = definitions if definitions is not None else _vocab.texts(spec.get("definition"), LANG)
        return (tagged("rdfs:comment", texts) + tagged("skos:definition", texts)
                + tagged("skos:scopeNote", _vocab.texts(spec.get("scope_note"), LANG))
                + tagged("skos:example", _vocab.texts(spec.get("example"), LANG)))

    def reasoning(section, name):
        """The recorded rationale, as meta: annotations; only what is recorded."""
        entry = (WHY.get(section) or {}).get(name) or {}
        out = ""
        for key, predicate in (("question", "meta:question"), ("why", "meta:rationale"),
                               ("alternatives", "meta:alternatives"), ("validated_by", "meta:validatedBy")):
            if (entry.get(key) or "").strip():
                out += f" ; {predicate} {q(entry[key].strip())}"
        return out

    def classes_of(spec):
        """A declared domain or range. Several classes are a union: written as a list of
        `rdfs:domain` values they would mean every one of them at once."""
        names = [t.strip() for t in spec.split("|") if t.strip()]
        if len(names) == 1:
            return terms.curie(names[0])
        return "[ a owl:Class ; owl:unionOf ( %s ) ]" % " ".join(terms.curie(t) for t in names)

    ttl = [f"@prefix {prefix}: <{iri}> ." for prefix, iri in terms.prefixes.items()]
    ttl += ["@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            f"@prefix skos: <{rdf.SKOS}> .",
            f"@prefix sh: <{rdf.SHACL}> .",
            f"@prefix meta: <{rdf.META}> .", "",
            f"{PREFIX}: a owl:Ontology ; rdfs:label {q(NAME + ' Ontology')} .", ""]
    for c, spec in CLASSES.items():
        parents = "".join(f" ; rdfs:subClassOf {terms.curie(parent)}" for parent in spec.get("subclass_of") or [])
        ttl.append(f"{terms.curie(c)} a owl:Class{labels(spec, c)}{parents}{notes(spec)}{reasoning('classes', c)} .")
    ttl.append("")
    for p, spec in PROPS.items():
        # A null domain or range is "any class" and is simply not asserted.
        line = f"{terms.curie(p)} a owl:ObjectProperty{labels(spec, p)}"
        if spec.get("domain"):
            line += f" ; rdfs:domain {classes_of(spec['domain'])}"
        if spec.get("range"):
            line += f" ; rdfs:range {classes_of(spec['range'])}"
        if spec.get("subproperty_of"):
            line += f" ; rdfs:subPropertyOf {terms.curie(spec['subproperty_of'])}"
        line += notes(spec)
        if spec.get("inverse"):
            line += f" ; owl:inverseOf {terms.curie(spec['inverse'], beside=p)}"
        ttl.append(line + reasoning("properties", p) + " .")
    # An inverse that is not a relation of its own is still a property: declared with its label,
    # so the reading "Payments platform contains Payment API" is in the RDF too.
    inverses = [(p, spec) for p, spec in PROPS.items() if spec.get("inverse") and spec["inverse"] not in PROPS]
    if inverses:
        ttl.append("")
        ttl.append("# --- inverses: the same relations read from the other side ---")
        for p, spec in inverses:
            inv = spec["inverse"]
            pref = _vocab.texts(spec.get("inverse_label"), LANG) or {LANG: _vocab.name_as_words(inv)}
            ttl.append(f"{terms.curie(inv, beside=p)} a owl:ObjectProperty{tagged('rdfs:label', pref)}{tagged('skos:prefLabel', pref)}"
                       f" ; owl:inverseOf {terms.curie(p)} .")
    if ATTRIBUTES:
        ttl.append("")
        ttl.append("# --- attributes: one property per name, its domain every class that declares it ---")
        for a, holders in ATTRIBUTE_HOLDERS.items():
            ranges = list(dict.fromkeys(xsd_of(spec["type"]) for _c, spec in holders))
            schemes = list(dict.fromkeys(scheme_of(spec["type"]) for _c, spec in holders))
            if len(holders) == 1:
                definitions = meaning(holders[0][1])
            else:                                 # one definition per class, each prefixed with the class
                definitions = {}
                for c, spec in holders:
                    for lang, d in meaning(spec).items():
                        definitions.setdefault(lang, [])
                        definitions[lang].append("%s: %s" % (c, d))
            # A list is written as an RDF collection, which is a resource, not a literal; a scheme's
            # values are its concepts, so the property is an object property onto them.
            if schemes != [None] and len(schemes) == 1:
                kind = "owl:ObjectProperty"
                rng = " ; rdfs:range [ a owl:Restriction ; owl:onProperty skos:inScheme ; owl:hasValue %s ]" % terms.curie(schemes[0])
            elif None not in schemes:                           # a scheme per class: the definitions say which
                kind, rng = "owl:ObjectProperty", " ; rdfs:range skos:Concept"
            elif any(schemes):
                kind, rng = "rdf:Property", ""
            elif ranges == ["rdf:List"]:
                kind, rng = "owl:ObjectProperty", " ; rdfs:range rdf:List"
            elif "rdf:List" in ranges:
                kind, rng = "rdf:Property", ""
            elif len(ranges) == 1:
                kind, rng = "owl:DatatypeProperty", f" ; rdfs:range {ranges[0]}"
            else:
                kind, rng = "owl:DatatypeProperty", " ; rdfs:range [ a rdfs:Datatype ; owl:unionOf ( %s ) ]" % " ".join(ranges)
            comments = {lang: d for lang, d in definitions.items()} if len(holders) == 1 else definitions
            comment_text = "".join(
                f" ; {predicate} " + " , ".join(q(d, lang) for lang, ds in comments.items() for d in (ds if isinstance(ds, list) else [ds]))
                for predicate in ("rdfs:comment", "skos:definition")) if comments else ""
            ttl.append(f"{terms.curie(a)} a {kind}{labels(holders[0][1], a)} ; "
                       f"rdfs:domain {classes_of('|'.join(c for c, _spec in holders))}{rng}{comment_text} .")
    if SCHEMES:
        ttl.append("")
        ttl.append("# --- controlled values: each scheme and its concepts ---")
        for name, scheme in SCHEMES.items():
            concepts = scheme.get("concepts") or {}
            tops = [k for k, c in concepts.items() if not c.get("broader")]
            ttl.append(f"{terms.curie(name)} a skos:ConceptScheme{labels(scheme, name)}{notes(scheme)}"
                       + (" ; skos:hasTopConcept " + " , ".join(concept(name, k) for k in tops) if tops else "") + " .")
            for key, c in concepts.items():
                line = f"{concept(name, key)} a skos:Concept{labels(c, key)}{notes(c)} ; skos:inScheme {terms.curie(name)}"
                if c.get("broader"):
                    line += f" ; skos:broader {concept(name, c['broader'])}"
                else:
                    line += f" ; skos:topConceptOf {terms.curie(name)}"
                ttl.append(line + " .")
    # ---- shapes: the declared constraints as SHACL, one node shape per constrained class ----
    by_class = {}
    for c, spec in CLASSES.items():
        for item in spec.get("requires") or []:
            if item in PROPS or item in ATTRIBUTE_HOLDERS:
                by_class.setdefault(c, []).append((item, 1, None, f"every {c} carries {item}"))
    for p, spec in PROPS.items():
        low, high = spec.get("min") or 0, spec.get("max")
        if not low and high is None:
            continue
        for c in [t.strip() for t in (spec.get("domain") or "").split("|") if t.strip()]:
            by_class.setdefault(c, []).append((p, low or None, high, f"a {c} has {_vocab_cardinality(spec)} {p}"))
    for c, attrs in ATTRIBUTES.items():
        for a, spec in attrs.items():
            if spec.get("required"):
                by_class.setdefault(c, []).append((a, 1, None, f"every {c} has {a}"))
    from ..reason import rules as _rules
    from . import sparql as _sparql
    policies = [r for r in _rules.load(project) if isinstance(r, dict) and r.get("kind") == "policy"]
    if by_class or policies:
        ttl.append("")
        ttl.append("# --- shapes: the constraints the graph is held to; `oto curate check` evaluates the same ones ---")
        for c in CLASSES:
            rows = by_class.get(c)
            if not rows:
                continue
            props = []
            for path, low, high, message in rows:
                parts = [f"sh:path {terms.curie(path)}"]
                if low:
                    parts.append(f"sh:minCount {low}")
                if high is not None:
                    parts.append(f"sh:maxCount {high}")
                parts.append(f"sh:message {q(message, LANG)}")
                props.append("sh:property [ %s ]" % " ; ".join(parts))
            ttl.append(f"{terms.curie(c + 'Shape')} a sh:NodeShape ; sh:targetClass {terms.curie(c)} ; " + " ; ".join(props) + " .")
    if policies:
        ttl.append("# policy rules, as SPARQL constraints: the focus node is the rule's first typed variable")
        for rule in policies:
            rendered = _sparql.policy_constraint(rule, _cfg, terms)
            if rendered is None:
                ttl.append("# policy %s is not rendered: its first pattern binds no class" % rule.get("id"))
                continue
            targets, select = rendered
            message = (rule.get("then") or {}).get("flag") or rule.get("id")
            if rule.get("answers"):
                message += " (answers %s)" % rule["answers"]
            severity = "sh:Violation" if rule.get("severity") == "blocking" else "sh:Warning"
            shape = terms.curie(re.sub(r"[^A-Za-z0-9]+", "_", rule["id"]).strip("_") + "Policy")
            ttl.append(f"{shape} a sh:NodeShape ; sh:targetClass " + " , ".join(terms.curie(t) for t in targets)
                       + f" ; sh:severity {severity} ; sh:sparql [ a sh:SPARQLConstraint ; sh:message {q(message, LANG)}"
                       + " ; sh:select \"\"\"%s\"\"\" ] ." % select.replace("\\", "\\\\"))
    ttl.append("")
    ttl.append("# --- temporal & provenance annotation properties: when a fact holds, and what it rests on ---")
    for t, spec in TEMPORAL.items():
        rng = ("xsd:date" if spec["type"] == "date" else "xsd:string") if spec["type"] != "ref" else None
        line = f"{terms.temporal_curie(t)} a owl:AnnotationProperty{labels(spec, t)}{notes(spec)}"
        if rng:
            line += f" ; rdfs:range {rng}"
        ttl.append(line + " .")
    ttl.append("")
    ttl.append("# --- the annotation properties the reasoning is recorded with ---")
    for name, comment in (("question", "The question a term exists to answer, in the asker's words."),
                          ("rationale", "Why the term is its own: why a class and not an attribute or a merge."),
                          ("alternatives", "What was considered instead, and why it was rejected."),
                          ("validatedBy", "The person who knows the domain and confirmed the term as written.")):
        ttl.append(f"meta:{name} a owl:AnnotationProperty ; rdfs:label {q(_vocab.name_as_words(name))} ; rdfs:comment {q(comment)} ; "
                   f"rdfs:isDefinedBy <{rdf.META.rstrip('#')}> .")
    open(os.path.join(ONT, f"{SLUG}.ttl"), "w", encoding="utf-8").write("\n".join(ttl) + "\n")

    # ---------- questions.yaml: the SPARQL rendering of each question ----------
    from . import sparql as _sparql
    yaml_path = os.path.join(ONT, "questions.yaml")
    if QUESTIONS:
        open(yaml_path, "w", encoding="utf-8").write(_sparql.questions_yaml(QUESTIONS, _cfg, terms, NAME, LANG))
    elif os.path.exists(yaml_path):
        os.remove(yaml_path)

    # ---------- JSON-LD context ----------
    def compact(curie):
        return curie.strip("<>")          # a name that is no local name is written as its full IRI

    ctx = {"@version": 1.1}
    ctx.update(terms.prefixes)
    ctx.update({"id": "@id", "type": "@type",
                "label": "rdfs:label", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "skos": rdf.SKOS, "meta": rdf.META})
    for c in CLASSES:
        ctx[c] = {"@id": compact(terms.curie(c))}          # so a node's `type` resolves to its class
    for p in PROPS:
        ctx[p] = {"@id": compact(terms.curie(p)), "@type": "@id"}
    for a, holders in ATTRIBUTE_HOLDERS.items():
        entry = {"@id": compact(terms.curie(a))}
        ranges = list(dict.fromkeys(xsd_of(spec["type"]) for _c, spec in holders))
        if any(scheme_of(spec["type"]) for _c, spec in holders):
            entry["@type"] = "@id"
        elif ranges == ["rdf:List"]:
            entry["@container"] = "@list"
        elif len(ranges) == 1:
            entry["@type"] = "http://www.w3.org/2001/XMLSchema#" + ranges[0].split(":")[1]
        ctx.setdefault(a, entry)
    for t, spec in TEMPORAL.items():
        if spec["type"] == "ref":
            ctx[t] = {"@id": compact(terms.temporal_curie(t)), "@type": "@id"}
        elif spec["type"] == "date":
            ctx[t] = {"@id": compact(terms.temporal_curie(t)), "@type": "http://www.w3.org/2001/XMLSchema#date"}
        else:
            ctx[t] = {"@id": compact(terms.temporal_curie(t))}
    jsonld = {"@context": ctx,
              "classes": [compact(terms.curie(c)) for c in CLASSES],
              "properties": [compact(terms.curie(p)) for p in PROPS],
              "attributes": {c: list(attrs) for c, attrs in ATTRIBUTES.items()},
              "temporal_properties": [compact(terms.temporal_curie(t)) for t in TEMPORAL]}
    json.dump(jsonld, open(os.path.join(ONT, f"{SLUG}.context.jsonld"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"ontology: {len(CLASSES)} classes, {len(PROPS)} properties")
    print("unmapped classes:", missing_cls or "none", "| unmapped props:", missing_prop or "none")
