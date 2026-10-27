# -*- coding: utf-8 -*-
"""The ontology as a navigable model (roadmap D1): the vocabulary projected into classes with their
parents, children, relations with cardinality and attributes, so a person browses the ontology itself
and not only the instances it types.

    model(vocabulary, counts=None)   {"version", "derived_from_data", "counts", "classes": [...], "relations": [...]}
    for_class(model, name)           one class's entry, or None

A class entry: name, label (the declared label, else the name as words), definition, parents (as
declared), ancestors (nearest first), children (direct, in name order), requires (the relations every
node of the class must carry), things (how many current nodes the store holds of exactly this class,
when counts are given), attributes (name, type, values for a controlled type, definition, required,
default, decision), relations_out (every relation whose domain is the class or one of its ancestors:
name, to, cardinality, inverse, definition, inherited_from) and relations_in (every relation whose
range reaches the class: name, from, inverse, inherited_from). A relation entry: name, domain, range,
inverse, cardinality, definition, subproperty_of, derived, things. The vocabulary is the payload's
(`serve/payload.py`), declared or derived from the data; a derived one has no attributes and no
hierarchy, and says so with `derived_from_data`. Served at /api/ontology, carried in the graph payload.
"""
from ..model import vocabulary as _vocab


def _words(name):
    """`DecisionRecord` -> "decision record"; an acronym (`NFR`) stays as written."""
    return str(name) if str(name).isupper() else _vocab.name_as_words(name)


def _text(value):
    return _vocab.text(value) if value else ""


def _attribute(name, spec, schemes):
    spec = spec or {}
    try:
        values = _vocab.concepts_of(spec.get("type"), schemes)
    except ValueError:
        values = None
    return {"name": name, "label": _text(spec.get("label")) or _words(name), "type": spec.get("type") or "string",
            "values": sorted(values) if values is not None else None, "definition": _text(spec.get("definition")),
            "required": spec.get("required") is True, "default": spec.get("default"), "decision": spec.get("decision") is True}


def model(vocabulary, counts=None):
    """The vocabulary as a navigable model. `counts` is the payload's counts ({"by_class", "by_relation"})."""
    vocabulary = vocabulary or {}
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    attributes = vocabulary.get("attributes") or {}
    schemes = vocabulary.get("schemes") or {}
    by_class = (counts or {}).get("by_class") or {}
    by_relation = (counts or {}).get("by_relation") or {}
    children = {name: [] for name in classes}
    for name in classes:
        for parent in _vocab.parents(classes, name):
            children.setdefault(parent, []).append(name)
    relations = []
    for name in sorted(properties):
        spec = properties[name] or {}
        relations.append({"name": name, "label": _text(spec.get("label")) or _words(name), "domain": list(_vocab._union(spec.get("domain"))),
                          "range": list(_vocab._union(spec.get("range"))), "inverse": spec.get("inverse"),
                          "inverse_label": _text(spec.get("inverse_label")) or (_words(spec["inverse"]) if spec.get("inverse") else None),
                          "cardinality": _vocab._cardinality(spec), "definition": _text(spec.get("definition")),
                          "subproperty_of": spec.get("subproperty_of"), "derived": bool(spec.get("derived")), "things": by_relation.get(name, 0)})
    out = []
    for name in sorted(classes):
        spec = classes[name] or {}
        ancestors = _vocab.ancestors(classes, name)
        lineage = [name] + ancestors
        relations_out, relations_in = [], []
        for rel in relations:
            holder = next((k for k in lineage if k in rel["domain"]), None)
            if holder is not None:
                relations_out.append({"name": rel["name"], "label": rel["label"], "to": rel["range"], "cardinality": rel["cardinality"],
                                      "inverse": rel["inverse"], "definition": rel["definition"], "inherited_from": None if holder == name else holder})
            reached = next((k for k in lineage if k in rel["range"]), None)
            if reached is not None:
                relations_in.append({"name": rel["name"], "label": rel["inverse_label"] or rel["label"], "from": rel["domain"], "inverse": rel["inverse"],
                                     "inherited_from": None if reached == name else reached})
        out.append({"name": name, "label": _text(spec.get("label")) or _words(name), "definition": _text(spec.get("definition")),
                    "scope_note": _text(spec.get("scope_note")), "example": _text(spec.get("example")),
                    "parents": _vocab.parents(classes, name), "ancestors": ancestors, "children": sorted(children.get(name) or []),
                    "requires": list(spec.get("requires") or []), "things": by_class.get(name, 0),
                    "attributes": [_attribute(a, s, schemes) for a, s in sorted((attributes.get(name) or {}).items())],
                    "relations_out": relations_out, "relations_in": relations_in})
    return {"version": vocabulary.get("ontology_version"), "derived_from_data": bool(vocabulary.get("derived_from_data")),
            "counts": {"classes": len(out), "relations": len(relations), "attributes": sum(len(c["attributes"]) for c in out),
                       "things": sum(by_class.values()) if by_class else None},
            "classes": out, "relations": relations}


def for_class(m, name):
    """One class's entry of a model, or None."""
    return next((c for c in (m or {}).get("classes") or [] if c["name"] == name), None)
