# -*- coding: utf-8 -*-
"""The vocabulary as an answer reads it: what each class, relation and attribute is called and
means, from the term rows a store carries (targets/rows.py) or a project declares, so the engine and the cards say
"part of → Payments platform" and "Component — a part of a system deployed as a unit" instead of
`part_of` and `Component`.

A term with no written label is read by its name (model/vocabulary.py), so nothing here depends
on an ontology having been given labels; a store built with no vocabulary at all still answers,
with names.
"""
import json

from . import vocabulary as _vocab


class Vocabulary:
    """Terms by kind: `classes`, `relations` (name -> spec), `attributes` ((class, name) -> spec),
    `temporal`, with the rationale beside each and the default language."""

    def __init__(self, rows=()):
        self.classes, self.relations, self.attributes, self.temporal, self.schemes = {}, {}, {}, {}, {}
        self.rationale, self.iri = {}, {}
        self.language = _vocab.DEFAULT_LANGUAGE
        self.languages = [self.language]
        for row in rows:
            spec = dict(row.get("spec") or {})
            declared = spec.pop("_languages", None)
            if declared:
                self.languages, self.language = list(declared), declared[0]
            kind, name, owner = row.get("kind"), row.get("name"), row.get("owner") or ""
            key = (owner, name) if kind == "attribute" else name
            {"class": self.classes, "relation": self.relations, "attribute": self.attributes,
             "temporal": self.temporal, "scheme": self.schemes}.get(kind, {})[key] = spec
            self.rationale[(kind, key)] = dict(row.get("rationale") or {})
            self.iri[(kind, key)] = row.get("iri")

    @classmethod
    def of_store(cls, store):
        return cls(store.terms() if "terms" in store.features() else [])

    @classmethod
    def of_project(cls, project):
        from ..targets.rows import term_rows
        return cls([dict(r, spec=json.loads(r["spec"]), rationale=json.loads(r["rationale"])) for r in term_rows(project)])

    # ---- reading ----
    def class_label(self, name, language=None):
        return _vocab.label(self.classes.get(name), name, language or self.language, self.language)

    def class_definition(self, name, language=None):
        return _vocab.text((self.classes.get(name) or {}).get("definition"), language or self.language, self.language)

    def relation_label(self, name, language=None):
        return _vocab.label(self.relations.get(name), name, language or self.language, self.language)

    def inverse_label(self, name, language=None):
        """How an edge reads from its target's side, or None when no inverse is declared."""
        spec = self.relations.get(name) or {}
        inverse = spec.get("inverse")
        if not inverse:
            return None
        written = _vocab.text(spec.get("inverse_label"), language or self.language, self.language)
        if written:
            return written
        declared = self.relations.get(inverse)             # the inverse may be a relation in its own right
        return _vocab.label(declared, inverse, language or self.language, self.language)

    def classed(self, name):
        """`Component — a part of a system deployed as a unit`, or the bare name without a definition."""
        definition = self.class_definition(name)
        return "%s — %s" % (name, definition) if definition else name

    # ---- the hierarchy ----
    def ancestors(self, name):
        return _vocab.ancestors(self.classes, name)

    def covers(self, name):
        """A question about `name` covers these classes: itself and every class that is a kind of it."""
        return sorted(_vocab.covers(self.classes).get(name, {name}))

    def relation_covers(self, name):
        return sorted(_vocab.relation_covers(self.relations).get(name, {name}))

    def attribute(self, owner, name):
        """The declaration of an attribute on a class, its own or an ancestor's, or None."""
        spec = self.attributes.get((owner, name))
        for ancestor in [] if spec else self.ancestors(owner):         # a parent's declaration applies
            spec = self.attributes.get((ancestor, name))
            if spec:
                break
        return spec

    def attribute_label(self, owner, name, language=None):
        return _vocab.label(self.attribute(owner, name), name, language or self.language, self.language)

    # ---- controlled values ----
    def scheme_of(self, owner, name):
        """The scheme an attribute's values come from, or None."""
        spec = self.attribute(owner, name) or {}
        return spec["type"][7:] if str(spec.get("type", "")).startswith("scheme:") else None

    def concept(self, scheme, key):
        return ((self.schemes.get(scheme) or {}).get("concepts") or {}).get(key)

    def value_text(self, owner, name, value, language=None):
        """A value as an answer shows it: a concept by its label and definition, anything else as it is."""
        scheme = self.scheme_of(owner, name)
        concept = self.concept(scheme, value) if scheme and isinstance(value, str) else None
        if concept is None:
            return str(value)
        label = _vocab.label(concept, value, language or self.language, self.language)
        definition = _vocab.text(concept.get("definition"), language or self.language, self.language)
        return "%s — %s" % (label, definition) if definition else label

    def top_of(self, scheme, key):
        return _vocab.top_concept((self.schemes.get(scheme) or {}).get("concepts") or {}, key)

    def scheme_holders(self, scheme):
        """The (class, attribute) pairs whose values come from `scheme`."""
        return [(owner, name) for (owner, name), spec in self.attributes.items() if spec.get("type") == "scheme:" + scheme]

    # ---- finding a term by name or label ----
    def find(self, term):
        """Every term `term` names: by name, then by label or alternative label in any language."""
        wanted = " ".join(str(term or "").split()).lower()
        if not wanted:
            return []
        out = []
        for kind, table in (("class", self.classes), ("relation", self.relations),
                            ("attribute", self.attributes), ("temporal", self.temporal), ("scheme", self.schemes)):
            for key, spec in table.items():
                name = key[1] if kind == "attribute" else key
                names = {name.lower(), _vocab.name_as_words(name)}
                names |= {t.lower() for t in _vocab.texts(spec.get("label"), self.language).values()}
                names |= {x.lower() for items in _vocab.alt_labels(spec.get("alt_labels"), self.language).values() for x in items}
                if kind == "relation":
                    names |= {t.lower() for t in _vocab.texts(spec.get("inverse_label"), self.language).values()}
                    if spec.get("inverse"):
                        names |= {spec["inverse"].lower(), _vocab.name_as_words(spec["inverse"])}
                if wanted in names:
                    out.append((kind, key))
        for scheme, spec in self.schemes.items():
            for key, concept in (spec.get("concepts") or {}).items():
                names = {key.lower(), _vocab.name_as_words(key)} | {t.lower() for t in _vocab.texts(concept.get("label"), self.language).values()}
                names |= {x.lower() for items in _vocab.alt_labels(concept.get("alt_labels"), self.language).values() for x in items}
                if wanted in names:
                    out.append(("concept", (scheme, key)))
        return out

    def describe(self, kind, key):
        """One term, every language, for `kg_define`: {kind, name, owner, iri, labels, alt_labels,
        definition, scope_note, example, domain, range, inverse, inverse_label, type, rationale}."""
        if kind == "concept":
            scheme, key = key
            spec = self.concept(scheme, key) or {}
            narrower = [k for k, c in ((self.schemes.get(scheme) or {}).get("concepts") or {}).items() if c.get("broader") == key]
            out = {"kind": "concept", "name": key, "owner": scheme, "iri": None, "language": self.language,
                   "labels": _vocab.texts(spec.get("label"), self.language) or {self.language: _vocab.name_as_words(key)},
                   "alt_labels": _vocab.alt_labels(spec.get("alt_labels"), self.language), "rationale": {},
                   "broader": _vocab.broader_chain(((self.schemes.get(scheme) or {}).get("concepts") or {}), key),
                   "narrower": narrower, "used_by": self.scheme_holders(scheme)}
            for field in ("definition", "scope_note", "example"):
                if spec.get(field):
                    out[field] = _vocab.texts(spec[field], self.language)
            return out
        table = {"class": self.classes, "relation": self.relations, "attribute": self.attributes,
                 "temporal": self.temporal, "scheme": self.schemes}[kind]
        spec = table[key]
        name, owner = (key[1], key[0]) if kind == "attribute" else (key, None)
        out = {"kind": kind, "name": name, "owner": owner, "iri": self.iri.get((kind, key)), "language": self.language,
               "labels": _vocab.texts(spec.get("label"), self.language) or {self.language: _vocab.name_as_words(name)},
               "alt_labels": _vocab.alt_labels(spec.get("alt_labels"), self.language),
               "rationale": self.rationale.get((kind, key)) or {}}
        for field in ("definition", "scope_note", "example", "inverse_label"):
            if spec.get(field):
                out[field] = _vocab.texts(spec[field], self.language)
        for field in ("domain", "range", "inverse", "type", "subclass_of", "subproperty_of"):
            if spec.get(field):
                out[field] = spec[field]
        if kind == "class":
            out["ancestors"] = self.ancestors(name)
            out["kinds"] = [k for k in self.covers(name) if k != name]
        if kind == "relation":
            out["specialises"] = _vocab.superproperties(self.relations, name)
            out["specialised_by"] = [r for r in self.relation_covers(name) if r != name]
        if kind == "scheme":
            out["concepts"] = [{"key": k, "label": _vocab.label(c, k, self.language, self.language),
                                "definition": _vocab.text(c.get("definition"), self.language, self.language),
                                "broader": c.get("broader")} for k, c in (spec.get("concepts") or {}).items()]
            out["used_by"] = self.scheme_holders(name)
        if kind == "relation" and spec.get("inverse") and "inverse_label" not in out:
            out["inverse_label"] = {self.language: self.inverse_label(name)}
        return out
