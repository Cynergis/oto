# -*- coding: utf-8 -*-
"""The capture schema: what an elicitation tool asks for, rendered from an ontology.

A tool that interviews a person (the PRD & Architecture Studio, or any form) needs to know what to
capture. Instead of carrying a form of its own, it reads `capture.json`, rendered from a pack or
a project's vocabulary:

- **sections**: the competency questions grouped by who asks them, each with its wording, why it
  exists, its gate, and the item types it needs. A section is a conversation: "the data team asks
  …"; a question with a `non_empty` gate must be answerable before the tool may continue.
- **types**: one per class, with its term IRI, label and definition, its fields (the attributes,
  typed, enums as choices, `required`), its links (the relations whose domain covers the class,
  with their targets and cardinality), and what it `requires`.

Every field and link carries `x-term`, the IRI of the term it captures, so what the tool collects
is already in the ontology's words and `curate propose` (curate/propose.py) turns it into facts
without a mapping anyone writes. Rendered beside `questions.yaml` on every build and by
`oto ontology capture --name <pack>`.
"""
import json

from ..model import vocabulary as _vocab
from ..model.namespaces import Terms
from ..reason import questions as _questions, shapes as _shapes

VERSION = 1


def render(config, questions, terms, name, release=None, language=None, namespace=None):
    """The capture schema as a dict. `namespace` is the pack's own; a project's is its `ont/`."""
    language = language or _vocab.languages(config)[0]
    classes = config.get("classes") or {}
    properties = config.get("properties") or {}
    cover = _vocab.covers(classes)
    cited = _questions.terms_cited(questions, config)

    def text(spec, key):
        found = _vocab.texts(spec.get(key), language)
        return found.get(language) or next(iter(found.values()), "") if found else ""

    types = {}
    for kind, spec in classes.items():
        fields = {}
        for attr, aspec in sorted(_vocab.declared_attributes(config, kind).items()):
            kind_of, options = _vocab.parse_attribute_type(aspec.get("type"), config.get("schemes") or {})
            field = {"x-term": terms.iri(attr), "type": kind_of, "label": _vocab.label(aspec, attr, language, language),
                     "definition": text(aspec, "definition"), "required": bool(aspec.get("required"))}
            if kind_of in ("enum", "scheme"):
                field["choices"] = list(_vocab.concepts_of(aspec.get("type"), config.get("schemes") or {}))
            fields[attr] = field
        links = {}
        for relation, rspec in sorted(properties.items()):
            domain = [t.strip() for t in (rspec.get("domain") or "").split("|") if t.strip()]
            if domain and not any(kind in cover.get(d, {d}) for d in domain):
                continue
            if not domain:
                continue
            link = {"x-term": terms.iri(relation), "label": _vocab.label(rspec, relation, language, language),
                    "definition": text(rspec, "definition"),
                    "to": [t.strip() for t in (rspec.get("range") or "").split("|") if t.strip()] or ["*"],
                    "min": rspec.get("min") or 0, "max": rspec.get("max")}
            if rspec.get("inverse"):
                link["inverse"] = rspec["inverse"]
            links[relation] = link
        types[kind] = {"x-term": terms.iri(kind), "label": _vocab.label(spec, kind, language, language),
                       "definition": text(spec, "definition"), "id_prefix": kind.lower(),
                       "kinds_of": sorted(k for k in cover.get(kind, {kind}) if k != kind),
                       "fields": fields, "links": links,
                       "requires": list(spec.get("requires") or []),
                       "asked_by": sorted({q for q in cited.get(kind, [])})}

    sections = []
    by_who = {}
    for qid, q in questions.items():
        by_who.setdefault(q.get("who") or "anyone", []).append(qid)
    for who, ids in by_who.items():
        asks = []
        for qid in ids:
            q = questions[qid]
            needed = sorted(t for t, qs in cited.items() if qid in qs and t in classes)
            asks.append({"id": qid, "question": q.get("question", ""), "why": q.get("why", ""),
                         "gate": q.get("gate", "non_empty"), "may_continue": q.get("gate", "non_empty") not in ("non_empty", "no_gaps"),
                         "params": {k: v.get("type") for k, v in (q.get("params") or {}).items()},
                         "captures": needed, "validated_by": q.get("validated_by", "")})
        sections.append({"who": who, "asks": asks})

    return {"capture_schema": VERSION, "pack": name, "release": release, "namespace": namespace or terms.project,
            "language": language,
            "_about": "What to capture, rendered from the ontology %s: sections are the questions by who asks them; "
                      "types are the classes with their fields and links, each carrying x-term. "
                      "`oto curate propose` turns a capture written against this into proposals." % name,
            "sections": sections, "types": types,
            "shapes": _shapes.declared(config)}


def write(path, schema):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def for_project(project):
    """The capture schema of a project's own vocabulary and questions."""
    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    identity = project.identity()
    return render(config, _questions.load(project), Terms(config, identity), identity["slug"])


def for_ontology(name, roots=None):
    """The capture schema of a composed ontology unit (a pack)."""
    from ..model import ontologies
    composed = ontologies.composed(name, roots=roots)
    config = composed["config"]
    manifest = composed["manifest"]
    identity = {"slug": name, "name": name, "prefix": name, "namespace": manifest.get("namespace") or "https://cynergis.ai/ont/%s#" % name}
    return render(config, composed["questions"], Terms(config, identity), name, release=manifest.get("release"),
                  namespace=manifest.get("namespace"))
