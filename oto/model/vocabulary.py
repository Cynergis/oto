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


#: Attribute types a class may declare: `"attributes": {"Claim": {"state": ["enum:open|closed", "..."]}}`.
#: A value form is [type, description]. Absent and empty values are always allowed; a declaration
#: says what a value must be when there is one.
ATTRIBUTE_TYPES = ("string", "number", "integer", "boolean", "date", "list")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_attribute_type(spec):
    """('enum', ['open', 'closed']) or ('date', None); raises ValueError for an unknown type."""
    spec = (spec or "").strip()
    if spec.startswith("enum:"):
        options = [x.strip() for x in spec[5:].split("|") if x.strip()]
        if not options:
            raise ValueError("enum with no options")
        return "enum", options
    if spec not in ATTRIBUTE_TYPES:
        raise ValueError("unknown attribute type %r (expected one of %s, or enum:a|b)"
                         % (spec, ", ".join(ATTRIBUTE_TYPES)))
    return spec, None


def check_value(spec, value):
    """Why `value` does not fit the declared type, or None. Absent values always fit."""
    if value is None or value == "":
        return None
    kind, options = parse_attribute_type(spec)
    if kind == "enum":
        return None if value in options else "expected one of %s" % "|".join(options)
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


def declaration_problems(classes, attributes):
    """What is wrong with an `attributes` section, before anything is checked against it."""
    problems = []
    for kind, declared in (attributes or {}).items():
        if kind not in classes:
            problems.append("attributes declared for undeclared class %r" % kind)
        if not isinstance(declared, dict):
            problems.append("attributes of %r must be a mapping of name to [type, description]" % kind)
            continue
        for name, spec in declared.items():
            if not isinstance(spec, (list, tuple)) or not spec:
                problems.append("attribute %s.%s must be [type, description]" % (kind, name))
                continue
            try:
                parse_attribute_type(spec[0])
            except ValueError as exc:
                problems.append("attribute %s.%s: %s" % (kind, name, exc))
    return problems


class Vocabulary:
    """Classes, properties, per-class attributes, and the version they were declared at."""

    def __init__(self, classes=None, properties=None, temporal=None, version=UNVERSIONED, name="",
                 attributes=None):
        self.classes = dict(classes or {})
        self.properties = {k: tuple(v) for k, v in (properties or {}).items()}
        self.temporal = dict(temporal or {})
        self.attributes = {k: {a: list(v) for a, v in (d or {}).items()} for k, d in (attributes or {}).items()}
        self.version = int(version or UNVERSIONED)
        self.name = name

    @classmethod
    def from_config(cls, config):
        return cls(classes=config.get("classes"), properties=config.get("properties"),
                   temporal=config.get("temporal"), version=config.get("ontology_version", UNVERSIONED),
                   name=config.get("name", ""), attributes=config.get("attributes"))

    def to_dict(self):
        out = {"ontology_version": self.version, "name": self.name,
               "classes": self.classes,
               "properties": {k: list(v) for k, v in self.properties.items()},
               "temporal": self.temporal}
        if self.attributes:
            out["attributes"] = self.attributes
        return out

    def attribute_type(self, kind, name):
        spec = (self.attributes.get(kind) or {}).get(name)
        return spec[0] if spec else None

    def domain(self, relation):
        spec = self.properties.get(relation)
        return _union(spec[0]) if spec else ()

    def range(self, relation):
        spec = self.properties.get(relation)
        return _union(spec[1]) if spec and len(spec) > 1 else ()


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


def diff(old, new):
    """Every change from `old` to `new`, most severe first."""
    changes = []

    for name in sorted(set(new.classes) - set(old.classes)):
        changes.append(Change("class added", Change.ADDITIVE, name, "new class"))
    for name in sorted(set(old.classes) - set(new.classes)):
        changes.append(Change("class removed", Change.BREAKING, name,
                              "nodes of this type are no longer declared"))
    for name in sorted(set(old.classes) & set(new.classes)):
        if old.classes[name] != new.classes[name]:
            changes.append(Change("class described", Change.COSMETIC, name, "description changed"))

    for name in sorted(set(new.properties) - set(old.properties)):
        changes.append(Change("relation added", Change.ADDITIVE, name, "new relation"))
    for name in sorted(set(old.properties) - set(new.properties)):
        changes.append(Change("relation removed", Change.BREAKING, name,
                              "edges using this relation are no longer declared"))
    for name in sorted(set(old.properties) & set(new.properties)):
        before, after = old.properties[name], new.properties[name]
        if _union(before[0]) != _union(after[0]):
            changes.append(Change("domain changed", Change.BREAKING, name,
                                  "%s -> %s" % (before[0], after[0])))
        if len(before) > 1 and len(after) > 1 and _union(before[1]) != _union(after[1]):
            changes.append(Change("range changed", Change.BREAKING, name,
                                  "%s -> %s" % (before[1], after[1])))
        b_inv = before[2] if len(before) > 2 else None
        a_inv = after[2] if len(after) > 2 else None
        if b_inv != a_inv:
            changes.append(Change("inverse changed", Change.ADDITIVE, name,
                                  "%s -> %s" % (b_inv, a_inv)))
        b_desc = before[3] if len(before) > 3 else ""
        a_desc = after[3] if len(after) > 3 else ""
        if b_desc != a_desc:
            changes.append(Change("relation described", Change.COSMETIC, name,
                                  "description changed"))

    for kind in sorted(set(old.attributes) | set(new.attributes)):
        before, after = old.attributes.get(kind) or {}, new.attributes.get(kind) or {}
        for name in sorted(set(after) - set(before)):
            changes.append(Change("attribute added", Change.ADDITIVE, "%s.%s" % (kind, name), "new attribute"))
        for name in sorted(set(before) - set(after)):
            changes.append(Change("attribute removed", Change.BREAKING, "%s.%s" % (kind, name),
                                  "nodes carrying it are no longer declared"))
        for name in sorted(set(before) & set(after)):
            if (before[name][0] or "") != (after[name][0] or ""):
                changes.append(Change("attribute type changed", Change.BREAKING, "%s.%s" % (kind, name),
                                      "%s -> %s" % (before[name][0], after[name][0])))
            elif len(before[name]) > 1 and len(after[name]) > 1 and before[name][1] != after[name][1]:
                changes.append(Change("attribute described", Change.COSMETIC, "%s.%s" % (kind, name),
                                      "description changed"))

    if old.temporal != new.temporal:
        changes.append(Change("temporal vocabulary changed", Change.ADDITIVE, "temporal",
                              "%d -> %d fields" % (len(old.temporal), len(new.temporal))))

    order = {Change.BREAKING: 0, Change.ADDITIVE: 1, Change.COSMETIC: 2}
    changes.sort(key=lambda c: (order[c.severity], c.kind, c.subject))
    return changes


def impact(changes, nodes, edges):
    """Fill in how many nodes or edges each breaking change touches."""
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
        declared = vocabulary.attributes.get(kind)
        if not declared:
            continue
        for key, value in (node.get("attributes") or {}).items():
            if key not in declared:
                undeclared[(kind, key)] = undeclared.get((kind, key), 0) + 1
                continue
            checked += 1
            problem = check_value(declared[key][0], value)
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
        if expect_from and actual_from not in expect_from:
            key = (relation, actual_from, "|".join(expect_from))
            domain_bad[key] = domain_bad.get(key, 0) + 1
        if expect_to and actual_to not in expect_to:
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
    return Vocabulary.from_config(payload)


def write_lock(project, vocabulary, rules=None):
    payload = vocabulary.to_dict()
    if rules is None:
        from ..reason import rules as _rules
        rules = _rules.load(project)
    payload["rules"] = rules
    payload["_about"] = ("The vocabulary as last accepted. `oto ontology check` diffs the current "
                         "config against this to report what a change breaks. Commit it with the "
                         "project. Update it with `oto ontology accept`.")
    path = lock_path(project)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path
