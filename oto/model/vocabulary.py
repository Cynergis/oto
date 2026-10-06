# -*- coding: utf-8 -*-
"""The declared vocabulary, and what changes to it cost.

A vocabulary is the schema. Changing it is a migration, and today nothing tells a team what a change
will break. This module answers three questions:

  * what changed since the vocabulary was last accepted (`diff`)
  * which nodes and edges a change breaks (`impact`)
  * does the graph actually respect the declared domain and range (`conformance`)

The third is not the same as the integrity gate. The gate checks that every type and relation is
*declared*. It never checked that an edge's endpoints match the declared domain and range. Measured on
a real project, 1,019 of 3,640 edges did not, and nobody knew.

That matters most for the RDF export, where `rdfs:domain` and `rdfs:range` are inference rules rather
than constraints: a reasoner reading the export would infer the wrong type for every one of those
edges. So conformance is REPORTED by default, not enforced. A project turns it into an error with
`"strict_domains": true` once it has cleaned up, because failing a build that was passing yesterday
teaches people to bypass the gate.
"""
import json
import re
import os

LOCK_NAME = "ontology.lock.json"
UNVERSIONED = 0


def _union(spec):
    """Declared domains and ranges may be a union written `A|B`."""
    return tuple(sorted(x.strip() for x in (spec or "").split("|") if x.strip()))


#: The one form of each declaration in `ontology.config.json`, and the keys it may carry:
#:
#:   classes     {"Claim": {"definition": "A request for payment under a policy.", "label": "claim",
#:                          "alt_labels": ["file"], "scope_note": "...", "example": "..."}}
#:   properties  {"filed_by": {"domain": "Claim", "range": "Party|Organization", "inverse": "filed",
#:                             "definition": "Who filed it.", "label": "filed by", "inverse_label": "filed"}}
#:   attributes  {"Claim": {"state": {"type": "enum:open|closed", "definition": "Where it is.", "label": "state"}}}
#:   temporal    {"asOf": {"type": "date", "definition": "When this fact was recorded.", "label": "as of"}}
#:
#: `domain` and `range` name one class or a union written `A|B`; an absent one means any class.
#: A text (`definition`, `label`, `inverse_label`, `scope_note`, `example`) is one string in the
#: default language, or a map of language to string; `alt_labels` is a list, or a map of language
#: to list. The default language is the first of the vocabulary's `languages`, English when none.
#: A term with no written label is read by its name: `DecisionRecord` as "decision record",
#: `part_of` as "part of". A class may be a kind of others (`"subclass_of": ["Asset"]`): every
#: question about Assets then covers Components, and an Asset's attributes apply to them. A
#: relation may specialise one (`"subproperty_of": "depends_on"`).
#:
#: Shapes, the constraints a graph is held to (reason/shapes.py), are declared beside the terms:
#: a relation's `min` and `max` are how many of it one subject carries (`"max": 1`: a Payment is
#: charged to at most one Coverage; `"min": 1`: every Claim claims under a Policy); an attribute's
#: `"required": true` means every instance of the class carries it; a class's `requires` lists
#: the attributes and relations every instance must carry. Tightening one is a breaking change.
#:
#: Controlled values are concepts of a scheme, or a bare enum when their meaning needs no words:
#:
#:   schemes     {"ClaimState": {"definition": "Where a claim is in its handling.",
#:                               "concepts": {"open": {"label": "Open", "definition": "Reported, not yet assessed."},
#:                                            "reopened": {"label": "Reopened", "broader": "open"}}}}
#:   attributes  {"Claim": {"state": {"type": "scheme:ClaimState", ...}}}      or  "type": "enum:open|closed"
#:
#: Inside the engine an enum is a scheme whose concepts carry nothing but their key.
TEXT = ("definition", "label", "inverse_label", "scope_note", "example")
KEYS = {"schemes": ("definition", "label", "alt_labels", "scope_note", "example", "concepts"),
        "concepts": ("definition", "label", "alt_labels", "scope_note", "example", "broader"),
        "classes": ("definition", "label", "alt_labels", "scope_note", "example", "subclass_of", "requires"),
        "properties": ("domain", "range", "inverse", "definition", "label", "inverse_label", "alt_labels",
                       "scope_note", "example", "subproperty_of", "min", "max"),
        "attributes": ("type", "definition", "label", "alt_labels", "scope_note", "example", "required"),
        "temporal": ("type", "definition", "label")}
TEMPORAL_TYPES = ("date", "string", "ref")
DEFAULT_LANGUAGE = "en"
LANGUAGE_OK = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def languages(config):
    """The languages a vocabulary is written in, the default first."""
    declared = [x for x in (config.get("languages") or []) if isinstance(x, str) and x]
    return declared or [DEFAULT_LANGUAGE]


def texts(value, default_language=DEFAULT_LANGUAGE):
    """A text as {language: string}: a bare string is the default language's."""
    if isinstance(value, str):
        return {default_language: value} if value else {}
    return {lang: text for lang, text in (value or {}).items() if isinstance(text, str) and text}


def text(value, language=DEFAULT_LANGUAGE, default_language=DEFAULT_LANGUAGE):
    """A text in one language, falling back to the default language, then to any."""
    found = texts(value, default_language)
    return found.get(language) or found.get(default_language) or next(iter(found.values()), "")


def alt_labels(value, default_language=DEFAULT_LANGUAGE):
    """Alternative labels as {language: [strings]}: a bare list is the default language's."""
    if isinstance(value, list):
        return {default_language: [x for x in value if isinstance(x, str) and x]} if value else {}
    return {lang: [x for x in (items or []) if isinstance(x, str) and x]
            for lang, items in (value or {}).items() if isinstance(items, list) and items}


def name_as_words(name):
    """`DecisionRecord` -> "decision record", `part_of` -> "part of", `asOf` -> "as of"."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name)).replace("_", " ").replace("-", " ")
    return " ".join(words.split()).lower()


def label(spec, name, language=DEFAULT_LANGUAGE, default_language=DEFAULT_LANGUAGE):
    """A term's label in one language: as written, or read from its name."""
    return text((spec or {}).get("label"), language, default_language) or name_as_words(name)

#: Attribute types a class may declare. Absent and empty values are always allowed; a declaration
#: says what a value must be when there is one.
ATTRIBUTE_TYPES = ("string", "number", "integer", "boolean", "date", "list")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_attribute_type(spec, schemes=None):
    """('enum', ['open', 'closed']), ('scheme', 'ClaimState') or ('date', None); raises ValueError
    for an unknown type, or a scheme the vocabulary does not declare when `schemes` is given."""
    spec = (spec or "").strip()
    if spec.startswith("enum:"):
        options = [x.strip() for x in spec[5:].split("|") if x.strip()]
        if not options:
            raise ValueError("enum with no options")
        return "enum", options
    if spec.startswith("scheme:"):
        name = spec[7:].strip()
        if not name:
            raise ValueError("scheme: names no scheme")
        if schemes is not None and name not in schemes:
            raise ValueError("scheme %r is not declared under `schemes`" % name)
        return "scheme", name
    if spec not in ATTRIBUTE_TYPES:
        raise ValueError("unknown attribute type %r (expected one of %s, enum:a|b, or scheme:<Name>)"
                         % (spec, ", ".join(ATTRIBUTE_TYPES)))
    return spec, None


def concepts_of(spec, schemes=None):
    """The controlled values a type allows, as {key: concept spec}: an enum's keys carry nothing,
    a scheme's carry what the scheme declares. None for a type that is not controlled."""
    kind, detail = parse_attribute_type(spec)
    if kind == "enum":
        return {key: {} for key in detail}
    if kind == "scheme":
        return dict(((schemes or {}).get(detail) or {}).get("concepts") or {})
    return None


def check_value(spec, value, schemes=None):
    """Why `value` does not fit the declared type, or None. Absent values always fit."""
    if value is None or value == "":
        return None
    kind, options = parse_attribute_type(spec, schemes)
    if kind in ("enum", "scheme"):
        allowed = concepts_of(spec, schemes)
        return None if value in allowed else "expected one of %s" % "|".join(allowed)
    if kind == "string":
        return None if isinstance(value, str) else "expected a string"
    if kind == "number":
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "expected a number"
    if kind == "integer":
        return None if isinstance(value, int) and not isinstance(value, bool) else "expected an integer"
    if kind == "boolean":
        return None if isinstance(value, bool) else "expected true or false"
    if kind == "date":
        return None if isinstance(value, str) and ISO_DATE.match(value) else "expected a YYYY-MM-DD date"
    if kind == "list":
        return None if isinstance(value, list) else "expected a list"
    return None


def _shape(section, label, spec):
    """Why one declaration is not in the form its section takes, or None."""
    allowed = KEYS[section]
    example = "{%s}" % ", ".join('"%s": ...' % key for key in allowed)
    if not isinstance(spec, dict):
        return "%s must be an object, %s" % (label, example)
    unknown = sorted(set(spec) - set(allowed))
    if unknown:
        return "%s carries unknown key(s) %s (it takes %s)" % (label, ", ".join(unknown), ", ".join(allowed))
    for key in allowed:
        value = spec.get(key)
        if value is None:
            continue
        if key == "concepts":
            continue                                   # scheme_problems checks them
        if key == "subclass_of":
            if not (isinstance(value, list) and all(isinstance(x, str) and x for x in value)):
                return "%s: `subclass_of` must be a list of class names" % label
        elif key == "requires":
            if not (isinstance(value, list) and all(isinstance(x, str) and x for x in value)):
                return "%s: `requires` must be a list of attribute or relation names" % label
        elif key in ("min", "max"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return "%s: `%s` must be a whole number" % (label, key)
            if key == "max" and spec.get("min") is not None and isinstance(spec.get("min"), int) and value < spec["min"]:
                return "%s: `max` is below `min`" % label
        elif key == "required":
            if not isinstance(value, bool):
                return "%s: `required` must be true or false" % label
        elif key == "alt_labels":
            ok = (isinstance(value, list) and all(isinstance(x, str) for x in value)) or \
                 (isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
                                                  for k, v in value.items()))
            if not ok:
                return "%s: `alt_labels` must be a list of strings, or a map of language to list" % label
        elif key in TEXT:
            if not (isinstance(value, str) or (isinstance(value, dict)
                                               and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()))):
                return "%s: `%s` must be text, or a map of language to text" % (label, key)
        elif not isinstance(value, str):
            return "%s: `%s` must be text" % (label, key)
    return None


# ---- the hierarchy ----

def parents(classes, kind):
    """The classes `kind` is declared a kind of, as written."""
    return list((classes.get(kind) or {}).get("subclass_of") or [])


def ancestors(classes, kind):
    """Every class `kind` is a kind of, nearest first, each once; a cycle ends where it started."""
    out, queue = [], parents(classes, kind)
    while queue:
        parent = queue.pop(0)
        if parent == kind or parent in out:
            continue
        out.append(parent)
        queue += parents(classes, parent)
    return out


def covers(classes):
    """{class: the classes a question about it covers}: itself and every class that is a kind of it."""
    out = {kind: {kind} for kind in classes}
    for kind in classes:
        for ancestor in ancestors(classes, kind):
            out.setdefault(ancestor, {ancestor}).add(kind)
    return out


def declared_attributes(config, kind):
    """The attributes a node of `kind` may carry: its own declarations, then its ancestors'."""
    attributes = config.get("attributes") or {}
    out = dict(attributes.get(kind) or {})
    for ancestor in ancestors(config.get("classes") or {}, kind):
        for name, spec in (attributes.get(ancestor) or {}).items():
            out.setdefault(name, spec)
    return out


def superproperties(properties, relation):
    """Every relation `relation` specialises, nearest first."""
    out, parent = [], (properties.get(relation) or {}).get("subproperty_of")
    while parent and parent != relation and parent not in out:
        out.append(parent)
        parent = (properties.get(parent) or {}).get("subproperty_of")
    return out


def relation_covers(properties):
    """{relation: itself and every relation that specialises it}."""
    out = {name: {name} for name in properties}
    for name in properties:
        for parent in superproperties(properties, name):
            out.setdefault(parent, {parent}).add(name)
    return out


def hierarchy_problems(config):
    """A parent that is not declared, or a class or relation that is a kind of itself."""
    out = []
    classes, properties = config.get("classes") or {}, config.get("properties") or {}
    for kind in classes:
        for parent in parents(classes, kind):
            if parent not in classes:
                out.append("class %r is a kind of %r, which is not declared" % (kind, parent))
            elif parent == kind or kind in ancestors(classes, parent):
                out.append("class %r is a kind of itself through %r" % (kind, parent))
    for name, spec in properties.items():
        parent = spec.get("subproperty_of")
        if parent and parent not in properties:
            out.append("relation %r specialises %r, which is not declared" % (name, parent))
        elif parent and (parent == name or name in superproperties(properties, parent)):
            out.append("relation %r specialises itself through %r" % (name, parent))
    return out


def shape_problems(config):
    """What is wrong with the form of a vocabulary's classes, properties, attributes and temporal terms."""
    problems = []
    declared = config.get("languages")
    if declared is not None and (not isinstance(declared, list) or not declared
                                 or not all(isinstance(x, str) and LANGUAGE_OK.match(x) for x in declared)):
        problems.append("languages must be a non-empty list of language tags such as [\"en\", \"fr\"]")
    attributes = config.get("attributes") or {}
    if not isinstance(attributes, dict) or not all(isinstance(v, dict) for v in attributes.values()):
        problems.append("attributes must map a class to its attributes, each {\"type\": ..., \"definition\": ...}")
    else:
        for kind, declared in attributes.items():
            for name, spec in declared.items():
                problem = _shape("attributes", "attribute %s.%s" % (kind, name), spec)
                if problem:
                    problems.append(problem)
    for section, noun in (("classes", "class"), ("properties", "relation"), ("temporal", "temporal term")):
        declared = config.get(section) or {}
        if not isinstance(declared, dict):
            problems.append("%s must map a name to its declaration" % section)
            continue
        for name, spec in declared.items():
            problem = _shape(section, "%s %r" % (noun, name), spec)
            if problem:
                problems.append(problem)
            elif section == "temporal" and spec.get("type") not in TEMPORAL_TYPES:
                problems.append("temporal term %r: type must be one of %s" % (name, ", ".join(TEMPORAL_TYPES)))
    return problems


def declaration_problems(classes, attributes, schemes=None):
    """What is wrong with an `attributes` section, before anything is checked against it. With
    `schemes`, a `scheme:` type must name one of them."""
    problems = []
    for kind, declared in (attributes or {}).items():
        if kind not in classes:
            problems.append("attributes declared for undeclared class %r" % kind)
        if not isinstance(declared, dict):
            problems.append("attributes of %r must map a name to {\"type\": ..., \"definition\": ...}" % kind)
            continue
        for name, spec in declared.items():
            problem = _shape("attributes", "attribute %s.%s" % (kind, name), spec)
            if problem:
                problems.append(problem)
                continue
            try:
                parse_attribute_type(spec.get("type"), schemes)
            except ValueError as exc:
                problems.append("attribute %s.%s: %s" % (kind, name, exc))
    return problems


def scheme_problems(config):
    """What is wrong with the `schemes` section: a concept whose broader concept is not in the
    scheme, or one that is broader than itself."""
    out = []
    schemes = config.get("schemes") or {}
    if not isinstance(schemes, dict):
        return ["schemes must map a name to {\"definition\": ..., \"concepts\": {...}}"]
    for name, scheme in schemes.items():
        problem = _shape("schemes", "scheme %r" % name, scheme) if isinstance(scheme, dict) else "scheme %r must be an object" % name
        if problem:
            out.append(problem)
            continue
        concepts = scheme.get("concepts")
        if not isinstance(concepts, dict) or not concepts:
            out.append("scheme %r declares no concepts" % name)
            continue
        for key, concept in concepts.items():
            problem = _shape("concepts", "concept %s.%s" % (name, key), concept)
            if problem:
                out.append(problem)
                continue
            broader = concept.get("broader")
            if broader and broader not in concepts:
                out.append("concept %s.%s is narrower than %r, which the scheme does not declare" % (name, key, broader))
            elif broader and key in broader_chain(concepts, broader):
                out.append("concept %s.%s is broader than itself through %r" % (name, key, broader))
    return out


def broader_chain(concepts, key):
    """Every concept `key` is narrower than, nearest first; the chain ends where it would repeat."""
    out, parent = [], (concepts.get(key) or {}).get("broader")
    while parent and parent != key and parent not in out:
        out.append(parent)
        parent = (concepts.get(parent) or {}).get("broader")
    return out


def top_concept(concepts, key):
    """The concept at the top of `key`'s broader chain: `key` itself when it has none."""
    chain = broader_chain(concepts, key)
    return chain[-1] if chain else key


class Vocabulary:
    """Classes, properties, per-class attributes, and the version they were declared at."""

    def __init__(self, classes=None, properties=None, temporal=None, version=UNVERSIONED, name="",
                 attributes=None, schemes=None):
        self.classes = {k: dict(v) for k, v in (classes or {}).items()}
        self.properties = {k: dict(v) for k, v in (properties or {}).items()}
        self.temporal = {k: dict(v) for k, v in (temporal or {}).items()}
        self.attributes = {k: {a: dict(v) for a, v in (d or {}).items()} for k, d in (attributes or {}).items()}
        self.schemes = {k: dict(v, concepts={c: dict(x) for c, x in (v.get("concepts") or {}).items()})
                        for k, v in (schemes or {}).items()}
        self.version = int(version or UNVERSIONED)
        self.name = name

    @classmethod
    def from_config(cls, config):
        return cls(classes=config.get("classes"), properties=config.get("properties"),
                   temporal=config.get("temporal"), version=config.get("ontology_version", UNVERSIONED),
                   name=config.get("name", ""), attributes=config.get("attributes"), schemes=config.get("schemes"))

    def to_dict(self):
        out = {"ontology_version": self.version, "name": self.name,
               "classes": self.classes,
               "properties": self.properties,
               "temporal": self.temporal}
        if self.attributes:
            out["attributes"] = self.attributes
        if self.schemes:
            out["schemes"] = self.schemes
        return out

    def concepts(self, spec):
        """The controlled values an attribute type allows, or None."""
        return concepts_of(spec, self.schemes)

    def attribute_type(self, kind, name):
        spec = self.declared_attributes(kind).get(name)
        return spec["type"] if spec else None

    def declared_attributes(self, kind):
        return declared_attributes({"classes": self.classes, "attributes": self.attributes}, kind)

    def ancestors(self, kind):
        return ancestors(self.classes, kind)

    def covers(self, kind):
        """The classes a question about `kind` covers: itself and every class that is a kind of it."""
        return covers(self.classes).get(kind, {kind})

    def relation_covers(self, relation):
        return relation_covers(self.properties).get(relation, {relation})

    def domain(self, relation):
        return _union((self.properties.get(relation) or {}).get("domain"))

    def range(self, relation):
        return _union((self.properties.get(relation) or {}).get("range"))


class Change:
    """One difference between two vocabularies."""

    #: A change that can invalidate existing nodes or edges.
    BREAKING = "breaking"
    #: A change that adds capability without invalidating anything.
    ADDITIVE = "additive"
    #: Wording only.
    COSMETIC = "cosmetic"

    __slots__ = ("kind", "severity", "subject", "detail", "affected")

    def __init__(self, kind, severity, subject, detail, affected=0):
        self.kind = kind
        self.severity = severity
        self.subject = subject
        self.detail = detail
        self.affected = affected

    def __repr__(self):
        return "%s %s %s" % (self.severity, self.kind, self.subject)


def _cardinality(spec):
    """A relation's declared cardinality as text: `1..1`, `0..*`, `1..*`."""
    low = spec.get("min") or 0
    high = spec.get("max")
    return "%d..%s" % (low, "*" if high is None else high)


def diff(old, new):
    """Every change from `old` to `new`, most severe first."""
    changes = []

    for name in sorted(set(new.classes) - set(old.classes)):
        changes.append(Change("class added", Change.ADDITIVE, name, "new class"))
    for name in sorted(set(old.classes) - set(new.classes)):
        changes.append(Change("class removed", Change.BREAKING, name,
                              "nodes of this type are no longer declared"))
    for name in sorted(set(old.classes) & set(new.classes)):
        before_parents, after_parents = set(parents(old.classes, name)), set(parents(new.classes, name))
        if before_parents - after_parents:
            changes.append(Change("superclass removed", Change.BREAKING, name,
                                  "no longer a kind of %s; questions about it stop covering this class"
                                  % "|".join(sorted(before_parents - after_parents))))
        if after_parents - before_parents:
            changes.append(Change("superclass added", Change.ADDITIVE, name,
                                  "now a kind of %s" % "|".join(sorted(after_parents - before_parents))))
        before_req, after_req = set(old.classes[name].get("requires") or []), set(new.classes[name].get("requires") or [])
        if after_req - before_req:
            changes.append(Change("class requires more", Change.BREAKING, name,
                                  "every %s must now carry %s" % (name, ", ".join(sorted(after_req - before_req)))))
        if before_req - after_req:
            changes.append(Change("class requires less", Change.ADDITIVE, name,
                                  "no longer requires %s" % ", ".join(sorted(before_req - after_req))))
        same_but_parents = {k: v for k, v in old.classes[name].items() if k not in ("subclass_of", "requires")} == \
            {k: v for k, v in new.classes[name].items() if k not in ("subclass_of", "requires")}
        if old.classes[name].get("definition") != new.classes[name].get("definition"):
            changes.append(Change("class described", Change.COSMETIC, name, "definition changed"))
        elif not same_but_parents:
            changes.append(Change("class relabelled", Change.COSMETIC, name, "labels or notes changed"))

    for name in sorted(set(new.properties) - set(old.properties)):
        changes.append(Change("relation added", Change.ADDITIVE, name, "new relation"))
    for name in sorted(set(old.properties) - set(new.properties)):
        changes.append(Change("relation removed", Change.BREAKING, name,
                              "edges using this relation are no longer declared"))
    for name in sorted(set(old.properties) & set(new.properties)):
        before, after = old.properties[name], new.properties[name]
        if old.domain(name) != new.domain(name):
            changes.append(Change("domain changed", Change.BREAKING, name,
                                  "%s -> %s" % (before.get("domain"), after.get("domain"))))
        if old.range(name) != new.range(name):
            changes.append(Change("range changed", Change.BREAKING, name,
                                  "%s -> %s" % (before.get("range"), after.get("range"))))
        before_min, after_min = before.get("min") or 0, after.get("min") or 0
        before_max, after_max = before.get("max"), after.get("max")
        if after_min > before_min or (after_max is not None and (before_max is None or after_max < before_max)):
            changes.append(Change("cardinality tightened", Change.BREAKING, name,
                                  "%s -> %s" % (_cardinality(before), _cardinality(after))))
        elif after_min < before_min or (before_max is not None and (after_max is None or after_max > before_max)):
            changes.append(Change("cardinality loosened", Change.ADDITIVE, name,
                                  "%s -> %s" % (_cardinality(before), _cardinality(after))))
        if before.get("inverse") != after.get("inverse"):
            changes.append(Change("inverse changed", Change.ADDITIVE, name,
                                  "%s -> %s" % (before.get("inverse"), after.get("inverse"))))
        if before.get("subproperty_of") != after.get("subproperty_of"):
            if before.get("subproperty_of"):
                changes.append(Change("superproperty removed", Change.BREAKING, name,
                                      "no longer specialises %s; questions about it stop covering this relation"
                                      % before["subproperty_of"]))
            else:
                changes.append(Change("superproperty added", Change.ADDITIVE, name, "now specialises %s" % after["subproperty_of"]))
        if (before.get("definition") or "") != (after.get("definition") or ""):
            changes.append(Change("relation described", Change.COSMETIC, name,
                                  "definition changed"))
        elif any(before.get(k) != after.get(k) for k in ("label", "inverse_label", "alt_labels", "scope_note", "example")):
            changes.append(Change("relation relabelled", Change.COSMETIC, name, "labels or notes changed"))

    for kind in sorted(set(old.attributes) | set(new.attributes)):
        before, after = old.attributes.get(kind) or {}, new.attributes.get(kind) or {}
        for name in sorted(set(after) - set(before)):
            changes.append(Change("attribute added", Change.ADDITIVE, "%s.%s" % (kind, name), "new attribute"))
        for name in sorted(set(before) - set(after)):
            changes.append(Change("attribute removed", Change.BREAKING, "%s.%s" % (kind, name),
                                  "nodes carrying it are no longer declared"))
        for name in sorted(set(before) & set(after)):
            if before[name].get("type") != after[name].get("type"):
                changes.append(Change("attribute type changed", Change.BREAKING, "%s.%s" % (kind, name),
                                      "%s -> %s" % (before[name].get("type"), after[name].get("type"))))
            elif bool(before[name].get("required")) != bool(after[name].get("required")):
                changes.append(Change("attribute required" if after[name].get("required") else "attribute optional",
                                      Change.BREAKING if after[name].get("required") else Change.ADDITIVE,
                                      "%s.%s" % (kind, name),
                                      "every %s must carry it" % kind if after[name].get("required") else "no longer required"))
            elif before[name].get("definition") != after[name].get("definition"):
                changes.append(Change("attribute described", Change.COSMETIC, "%s.%s" % (kind, name),
                                      "definition changed"))

    for name in sorted(set(new.schemes) - set(old.schemes)):
        changes.append(Change("scheme added", Change.ADDITIVE, name, "new scheme"))
    for name in sorted(set(old.schemes) - set(new.schemes)):
        changes.append(Change("scheme removed", Change.BREAKING, name, "values of this scheme are no longer declared"))
    for name in sorted(set(old.schemes) & set(new.schemes)):
        before, after = old.schemes[name]["concepts"], new.schemes[name]["concepts"]
        for key in sorted(set(after) - set(before)):
            changes.append(Change("concept added", Change.ADDITIVE, "%s.%s" % (name, key), "new value"))
        for key in sorted(set(before) - set(after)):
            changes.append(Change("concept removed", Change.BREAKING, "%s.%s" % (name, key),
                                  "values that use it are no longer declared"))
        for key in sorted(set(before) & set(after)):
            if before[key].get("broader") != after[key].get("broader"):
                changes.append(Change("concept re-parented", Change.ADDITIVE, "%s.%s" % (name, key),
                                      "%s -> %s" % (before[key].get("broader"), after[key].get("broader"))))
            elif before[key] != after[key]:
                changes.append(Change("concept described", Change.COSMETIC, "%s.%s" % (name, key), "labels or notes changed"))
        if {k: v for k, v in old.schemes[name].items() if k != "concepts"} != {k: v for k, v in new.schemes[name].items() if k != "concepts"}:
            changes.append(Change("scheme described", Change.COSMETIC, name, "labels or notes changed"))

    if old.temporal != new.temporal:
        changes.append(Change("temporal vocabulary changed", Change.ADDITIVE, "temporal",
                              "%d -> %d fields" % (len(old.temporal), len(new.temporal))))

    order = {Change.BREAKING: 0, Change.ADDITIVE: 1, Change.COSMETIC: 2}
    changes.sort(key=lambda c: (order[c.severity], c.kind, c.subject))
    return changes


def impact(changes, nodes, edges, vocabulary=None):
    """Fill in how many nodes or edges each breaking change touches. `vocabulary` is the one the
    changes lead to, for what a class or relation covers."""
    new_classes = vocabulary.classes if vocabulary else {}
    new_properties = vocabulary.properties if vocabulary else {}
    node_types = {}
    for node in nodes:
        node_types[node.get("type")] = node_types.get(node.get("type"), 0) + 1
    edge_rels = {}
    for edge in edges:
        edge_rels[edge.get("rel")] = edge_rels.get(edge.get("rel"), 0) + 1

    carrying = {}
    for node in nodes:
        for key in (node.get("attributes") or {}):
            subject = "%s.%s" % (node.get("type"), key)
            carrying[subject] = carrying.get(subject, 0) + 1

    for change in changes:
        if change.kind == "class removed":
            change.affected = node_types.get(change.subject, 0)
        elif change.kind == "superclass removed":
            change.affected = sum(count for kind, count in node_types.items() if kind == change.subject or change.subject in ancestors(new_classes, kind))
        elif change.kind in ("concept removed", "scheme removed"):
            scheme, _, key = change.subject.partition(".")
            typed = "scheme:" + scheme
            change.affected = sum(1 for node in nodes for name, value in (node.get("attributes") or {}).items()
                                  if (vocabulary.attribute_type(node.get("type"), name) if vocabulary else None) == typed
                                  and (not key or value == key))
        elif change.kind == "superproperty removed":
            change.affected = sum(count for rel, count in edge_rels.items() if rel == change.subject or change.subject in superproperties(new_properties, rel))
        elif change.kind in ("relation removed", "domain changed", "range changed"):
            change.affected = edge_rels.get(change.subject, 0)
        elif change.kind in ("attribute removed", "attribute type changed"):
            change.affected = carrying.get(change.subject, 0)
    return changes


def attribute_conformance(vocabulary, nodes):
    """Do node attributes match their class's declarations?

    A class with no declarations is unconstrained. A class with declarations constrains the type of
    every declared attribute it carries, and reports the keys it carries that nobody declared.
    """
    mistyped, undeclared = [], {}
    checked = 0
    for node in nodes:
        kind = node.get("type")
        declared = vocabulary.declared_attributes(kind)
        if not declared:
            continue
        for key, value in (node.get("attributes") or {}).items():
            if key not in declared:
                undeclared[(kind, key)] = undeclared.get((kind, key), 0) + 1
                continue
            checked += 1
            problem = check_value(declared[key]["type"], value, vocabulary.schemes)
            if problem:
                mistyped.append((node.get("id"), key, problem, value))
    return {"checked": checked, "mistyped": mistyped,
            "undeclared": sorted(undeclared.items(), key=lambda kv: (-kv[1], kv[0]))}


def conformance(vocabulary, nodes, edges):
    """Do the edges respect the declared domain and range?

    Returns a dict with counts and, per relation, the concrete mismatches. Only relations that ARE
    declared are checked; undeclared ones are the integrity gate's job.
    """
    types = {n.get("id"): n.get("type") for n in nodes}
    checked = 0
    domain_bad = {}
    range_bad = {}
    for edge in edges:
        relation = edge.get("rel")
        if relation not in vocabulary.properties:
            continue
        checked += 1
        expect_from = vocabulary.domain(relation)
        expect_to = vocabulary.range(relation)
        actual_from = types.get(edge.get("from"))
        actual_to = types.get(edge.get("to"))
        fits = lambda actual, expected: actual in expected or any(a in expected for a in vocabulary.ancestors(actual))  # noqa: E731
        if expect_from and not fits(actual_from, expect_from):
            key = (relation, actual_from, "|".join(expect_from))
            domain_bad[key] = domain_bad.get(key, 0) + 1
        if expect_to and not fits(actual_to, expect_to):
            key = (relation, actual_to, "|".join(expect_to))
            range_bad[key] = range_bad.get(key, 0) + 1

    return {
        "checked": checked,
        "domain_violations": sum(domain_bad.values()),
        "range_violations": sum(range_bad.values()),
        "domain_patterns": sorted(domain_bad.items(), key=lambda kv: -kv[1]),
        "range_patterns": sorted(range_bad.items(), key=lambda kv: -kv[1]),
    }


# ---- the lock ----

def lock_path(project):
    return os.path.join(project.data, LOCK_NAME)


def read_lock(project):
    """The last accepted vocabulary, or None when a project has never accepted one."""
    path = lock_path(project)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    vocabulary = Vocabulary.from_config(payload)
    vocabulary.rationale = payload.get("rationale") or {}
    return vocabulary


def reconfirm(locked, current, rationale):
    """The classes and relations a person confirmed before their definition changed. The
    confirmation covered the text it was given; it does not cover this one until they say so."""
    out = []
    for section, before, after in (("classes", locked.classes, current.classes), ("properties", locked.properties, current.properties)):
        for name in sorted(set(before) & set(after)):
            if before[name].get("definition") == after[name].get("definition"):
                continue
            entry = (rationale.get(section) or {}).get(name) or {}
            then = ((getattr(locked, "rationale", None) or {}).get(section) or {}).get(name) or {}
            by = (entry.get("validated_by") or "").strip()
            if by and by == (then.get("validated_by") or "").strip():
                out.append(("class" if section == "classes" else "relation", name, by))
    return out


def write_lock(project, vocabulary, rules=None, questions=None):
    payload = vocabulary.to_dict()
    if rules is None:
        from ..reason import rules as _rules
        rules = _rules.load(project)
    payload["rules"] = rules
    if questions is None:
        from ..reason import questions as _questions
        questions = _questions.load(project)
    payload["questions"] = questions
    from . import rationale as _rationale
    payload["rationale"] = _rationale.load(project)
    payload["_about"] = ("The vocabulary as last accepted. `oto ontology check` diffs the current "
                         "config against this to report what a change breaks. Commit it with the "
                         "project. Update it with `oto ontology accept`.")
    path = lock_path(project)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path
