# -*- coding: utf-8 -*-
"""Shapes: the constraints a graph is held to, declared beside the terms and evaluated in the engine.

Three declarations in `ontology.config.json` are shapes (model/vocabulary.py):

    "properties":  {"charged_to": {"domain": "Payment", "range": "Coverage", "min": 1, "max": 1, ...}}
    "attributes":  {"Claim": {"claim_number": {"type": "string", "required": true, ...}}}
    "classes":     {"Component": {"requires": ["part_of", "runs_in"], ...}}

A relation's `min` and `max` count what one subject of its domain carries; an attribute's
`required` means every instance of the class carries a value; a class's `requires` names the
attributes and relations every instance must carry. A constraint on a class applies to the kinds
of it, as everywhere else. Policy rules (`rules.json`, kind `policy`) are the fourth source of
shape, and may say which question they protect (`"answers": "CQ3"`).

`findings` evaluates the declared constraints over a graph; `oto curate check` reports each one
as blocking, `oto ontology check` prints them for the live graph, and the self-check holds an
ontology's sample to them. The export writes them as SHACL (compile/ontology.py); the engine never
reads SHACL.
"""
from ..model.vocabulary import ancestors, covers as _covers, declared_attributes, relation_covers, _union


def _applies(relation_spec, kind, cover):
    """Does a relation declared on `domain` constrain nodes of class `kind`?"""
    domain = _union(relation_spec.get("domain"))
    if not domain:
        return False
    return any(kind in cover.get(d, {d}) for d in domain)


def declared(vocabulary):
    """Every shape the vocabulary declares, as rows: {kind, subject, class, ...}. What the export
    renders and what `oto ontology check` counts."""
    out = []
    for name, spec in sorted((vocabulary.get("classes") or {}).items()):
        for item in spec.get("requires") or []:
            out.append({"kind": "requires", "class": name, "subject": item})
    for name, spec in sorted((vocabulary.get("properties") or {}).items()):
        if spec.get("min") is not None and spec["min"] > 0:
            out.append({"kind": "min", "class": spec.get("domain") or "", "subject": name, "count": spec["min"]})
        if spec.get("max") is not None:
            out.append({"kind": "max", "class": spec.get("domain") or "", "subject": name, "count": spec["max"]})
    for kind, attrs in sorted((vocabulary.get("attributes") or {}).items()):
        for name, spec in sorted(attrs.items()):
            if spec.get("required"):
                out.append({"kind": "required", "class": kind, "subject": name})
    return out


def problems(vocabulary):
    """What is wrong with the declared shapes, before anything is evaluated: a `requires` naming
    nothing the class carries, a `min` on a relation with no domain."""
    out = []
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    cover = _covers(classes)
    for name, spec in classes.items():
        attrs = declared_attributes(vocabulary, name)
        for item in spec.get("requires") or []:
            if item in attrs:
                continue
            relation = properties.get(item)
            if relation is None:
                out.append("class %r requires %r, which is neither an attribute it declares nor a relation" % (name, item))
            elif not _applies(relation, name, cover):
                out.append("class %r requires relation %r, whose domain (%s) does not cover it"
                           % (name, item, relation.get("domain") or "any class"))
    for name, spec in properties.items():
        if (spec.get("min") or spec.get("max") is not None) and not _union(spec.get("domain")):
            out.append("relation %r declares min or max but no domain: a count needs a subject class" % name)
    return out


def rule_question_problems(rules, questions):
    """A policy rule's `answers` must name a declared question."""
    out = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        answers = rule.get("answers")
        if answers is None:
            continue
        if not isinstance(answers, str) or not answers.strip():
            out.append("rule %r: `answers` must be a question id" % rule.get("id"))
        elif answers not in (questions or {}):
            out.append("rule %r answers %r, which questions.json does not declare" % (rule.get("id"), answers))
        if rule.get("kind") != "policy" and answers is not None:
            out.append("rule %r: only a policy rule answers a question" % rule.get("id"))
    return out


def _present(value):
    return value is not None and value != "" and value != [] and value != {}


def findings(vocabulary, nodes, edges, derived_attributes=None):
    """Every node that breaks a declared shape, in id order: {kind, node, class, subject, message}.
    Current nodes and current edges only (a superseded fact constrains nothing)."""
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    cover = _covers(classes)
    rel_cover = relation_covers(properties)
    derived_attributes = derived_attributes or {}
    current = [n for n in nodes if n.get("id") and n.get("status", "current") == "current"]
    ids = {n["id"] for n in current}
    out_count = {}
    for e in edges:
        if e.get("status", "current") == "superseded" or e.get("from") not in ids or e.get("to") not in ids:
            continue
        out_count.setdefault(e["from"], {}).setdefault(e["rel"], 0)
        out_count[e["from"]][e["rel"]] += 1

    def count(nid, relation):
        return sum(n for rel, n in out_count.get(nid, {}).items() if rel in rel_cover.get(relation, {relation}))

    def value(node, name):
        v = (node.get("attributes") or {}).get(name)
        if v is None:
            v = derived_attributes.get(node["id"], {}).get(name)
        return v

    out = []
    for node in sorted(current, key=lambda n: n["id"]):
        nid, kind = node["id"], node.get("type")
        if kind not in classes:
            continue
        lineage = [kind] + ancestors(classes, kind)
        attrs = declared_attributes(vocabulary, kind)
        for name, spec in sorted(attrs.items()):
            if spec.get("required") and not _present(value(node, name)):
                out.append({"kind": "required", "node": nid, "class": kind, "subject": name,
                            "message": "%s %s has no %s; every %s must" % (kind, nid, name, kind)})
        for relation, spec in sorted(properties.items()):
            if not _applies(spec, kind, cover):
                continue
            low, high = spec.get("min") or 0, spec.get("max")
            if not low and high is None:
                continue
            n = count(nid, relation)
            if n < low:
                out.append({"kind": "min", "node": nid, "class": kind, "subject": relation,
                            "message": "%s %s has %d %s; at least %d declared" % (kind, nid, n, relation, low)})
            if high is not None and n > high:
                out.append({"kind": "max", "node": nid, "class": kind, "subject": relation,
                            "message": "%s %s has %d %s; at most %d declared" % (kind, nid, n, relation, high)})
        seen = set()
        for ancestor in lineage:
            for item in (classes.get(ancestor) or {}).get("requires") or []:
                if item in seen:
                    continue
                seen.add(item)
                if item in attrs:
                    ok = _present(value(node, item))
                elif item in properties:
                    ok = count(nid, item) > 0
                else:
                    continue                                  # problems() reports the declaration
                if not ok:
                    out.append({"kind": "requires", "node": nid, "class": kind, "subject": item,
                                "message": "%s %s carries no %s; every %s requires it" % (kind, nid, item, ancestor)})
    return out


def findings_text(items, limit=20):
    if not items:
        return "shapes: every node satisfies the declared constraints"
    lines = ["shapes: %d violation(s):" % len(items)]
    for item in items[:limit]:
        lines.append("  [%-8s] %s" % (item["kind"], item["message"]))
    if len(items) > limit:
        lines.append("  ... and %d more" % (len(items) - limit))
    return "\n".join(lines)
