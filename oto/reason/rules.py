# -*- coding: utf-8 -*-
"""The rule language, and what makes a rule set usable.

A rule is vocabulary: declared in `rules.json` beside the ontology, with a reason and a place for
the person who confirmed it, versioned in the same lock. The language is small on purpose:

    {"id": "risk-reaches-system", "kind": "derive",
     "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
     "then": {"edge": ["r", "threatens", "s"]},
     "why": "A risk to a component is a risk to its system.", "validated_by": ""}

    {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
     "when": [{"node": "d", "type": "DecisionRecord"}, {"not_edge": ["d", "documented_in", "*"]}],
     "then": {"flag": "an architecture decision must cite the document that records it"},
     "why": "A decision nobody can open is a rumour."}

Patterns: `node` (a variable, optionally a class or `A|B`, optionally `where` conditions on its
declared attributes or on the node's own fields: status, as_of, valid_from, valid_to,
source_doc; a date may be compared with `$today` or `$today-<n>d`), `edge` (from, relation or
`a|b`, to; `*` is any), and, in policy rules only, `not_edge` and `not_node`. A derivation sees
current facts only; a policy also sees `intended` ones, so it can flag a plan gone stale. Actions: `edge`, `attribute` [var, name, value], or `flag`.
Derivation rules are positive, so a fixpoint exists; policy rules produce findings that never
feed back, so negation is safe there.
"""
import json
import os

NAME = "rules.json"
KINDS = ("derive", "policy")
SEVERITIES = ("warn", "blocking")
OPERATORS = ("=", "!=", "<", "<=", ">", ">=", "in", "contains")
ORDERED_TYPES = ("number", "integer", "date")
_MISSING = object()


def path_for(project):
    return os.path.join(project.data, NAME)


def load(project):
    """The rules on record, or an empty list when the project declares none."""
    path = path_for(project)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload.get("rules") or []) if isinstance(payload, dict) else list(payload)


def save(project, rules):
    with open(path_for(project), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_about": "Rules over the graph. `kind: derive` adds facts marked as derived, with "
                             "the rule and the premises; `kind: policy` flags what a policy forbids. "
                             "Declared here, reasoned about in `why`, confirmed in `validated_by`.",
                   "rules": rules}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _split(spec):
    return [x.strip() for x in str(spec or "").split("|") if x.strip()]


def _variables(rule):
    """Variables the `when` patterns bind (a `*` binds nothing; a negated pattern binds nothing)."""
    bound = set()
    for pattern in rule.get("when") or []:
        if "node" in pattern:
            bound.add(pattern["node"])
        elif "edge" in pattern:
            bound.update(v for v in (pattern["edge"][0], pattern["edge"][2]) if v != "*")
    return bound


def problems(rules, vocabulary):
    """What is wrong with a rule set, before anything runs. Empty means usable."""
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    attributes = vocabulary.get("attributes") or {}
    out = []
    seen = set()

    for number, rule in enumerate(rules, 1):
        rid = rule.get("id") if isinstance(rule, dict) else None
        label = "rule %r" % rid if rid else "rule %d" % number
        if not isinstance(rule, dict) or not rid:
            out.append("%s has no id" % label)
            continue
        if rid in seen:
            out.append("%s: duplicate id" % label)
        seen.add(rid)
        kind = rule.get("kind")
        if kind not in KINDS:
            out.append("%s: kind must be derive or policy, not %r" % (label, kind))
            continue
        if kind == "policy" and rule.get("severity", "warn") not in SEVERITIES:
            out.append("%s: severity must be warn or blocking" % label)
        if not (rule.get("why") or "").strip():
            out.append("%s has no `why`: a rule with no recorded reason cannot be reviewed" % label)

        when = rule.get("when")
        if not isinstance(when, list) or not when:
            out.append("%s: `when` must be a non-empty list of patterns" % label)
            continue
        var_types = {}
        for pattern in when:
            if not isinstance(pattern, dict) or len(pattern) < 1:
                out.append("%s: a pattern must be an object" % label)
                continue
            if "node" in pattern:
                for kind_name in _split(pattern.get("type")):
                    if kind_name not in classes:
                        out.append("%s: class %r is not declared" % (label, kind_name))
                if pattern.get("type"):
                    var_types[pattern["node"]] = _split(pattern["type"])
                out += _condition_problems(label, pattern, attributes, classes)
            elif "edge" in pattern or "not_edge" in pattern:
                key = "edge" if "edge" in pattern else "not_edge"
                spec = pattern[key]
                if not isinstance(spec, list) or len(spec) != 3:
                    out.append("%s: %s must be [from, relation, to]" % (label, key))
                    continue
                for relation in _split(spec[1]):
                    if relation not in properties:
                        out.append("%s: relation %r is not declared" % (label, relation))
                if key == "not_edge" and kind != "policy":
                    out.append("%s: not_edge is allowed in policy rules only; a derivation must stay positive" % label)
            elif "not_node" in pattern:
                if kind != "policy":
                    out.append("%s: not_node is allowed in policy rules only" % label)
                for kind_name in _split(pattern.get("type")):
                    if kind_name not in classes:
                        out.append("%s: class %r is not declared" % (label, kind_name))
            else:
                out.append("%s: unknown pattern %s" % (label, sorted(pattern)))

        then = rule.get("then")
        if not isinstance(then, dict) or len(then) != 1:
            out.append("%s: `then` must be exactly one action" % label)
            continue
        action = next(iter(then))
        bound = _variables(rule)
        if kind == "derive":
            if action == "edge":
                spec = then["edge"]
                if not isinstance(spec, list) or len(spec) != 3:
                    out.append("%s: then.edge must be [from, relation, to]" % label)
                else:
                    if spec[1] not in properties:
                        out.append("%s: derived relation %r is not declared" % (label, spec[1]))
                    for var in (spec[0], spec[2]):
                        if var not in bound:
                            out.append("%s: variable %r in `then` is not bound in `when`" % (label, var))
            elif action == "attribute":
                spec = then["attribute"]
                if not isinstance(spec, list) or len(spec) != 3:
                    out.append("%s: then.attribute must be [var, name, value]" % label)
                else:
                    var, name = spec[0], spec[1]
                    if var not in bound:
                        out.append("%s: variable %r in `then` is not bound in `when`" % (label, var))
                    for kind_name in var_types.get(var, []):
                        declared = attributes.get(kind_name)
                        if declared and name not in declared:
                            out.append("%s: %s declares its attributes and %r is not one of them" % (label, kind_name, name))
            else:
                out.append("%s: a derive rule's action must be edge or attribute" % label)
        else:
            if action != "flag" or not isinstance(then["flag"], str) or not then["flag"].strip():
                out.append("%s: a policy rule's action must be a `flag` message" % label)
    return out


def _condition_problems(label, pattern, attributes, classes=None):
    classes = classes or {}
    out = []
    where = pattern.get("where") or {}
    if not isinstance(where, dict):
        return ["%s: `where` must be an object of attribute conditions" % label]
    declared = {}
    from .. import model as _model  # noqa: F401  (the vocabulary module, for inherited declarations)
    from ..model.vocabulary import declared_attributes
    for kind_name in _split(pattern.get("type")):
        declared.update(declared_attributes({"classes": classes, "attributes": attributes}, kind_name))
    from .match import BUILTIN_FIELDS
    for name, condition in where.items():
        if name in BUILTIN_FIELDS:
            declared_type = "date" if name in ("as_of", "valid_from", "valid_to") else "string"
        else:
            declared_type = (declared.get(name) or {}).get("type")
        if isinstance(condition, dict):
            for op in condition:
                if op not in OPERATORS:
                    out.append("%s: operator %r on %s is not one of %s" % (label, op, name, ", ".join(OPERATORS)))
                elif declared_type and op in ("<", "<=", ">", ">=") and declared_type not in ORDERED_TYPES:
                    out.append("%s: %r on %s, which is declared %s, not a number or date" % (label, op, name, declared_type))
        elif pattern.get("type") and declared and declared_type is None and name not in BUILTIN_FIELDS:
            out.append("%s: attribute %r is not declared for %s" % (label, name, pattern.get("type")))
    return out


def diff(old, new):
    """(added ids, removed ids, changed ids). A changed `then` or `when` is a different rule."""
    old_by = {r["id"]: r for r in old if isinstance(r, dict) and r.get("id")}
    new_by = {r["id"]: r for r in new if isinstance(r, dict) and r.get("id")}
    added = sorted(set(new_by) - set(old_by))
    removed = sorted(set(old_by) - set(new_by))
    changed = sorted(rid for rid in set(old_by) & set(new_by)
                     if (old_by[rid].get("when"), old_by[rid].get("then"), old_by[rid].get("kind"), old_by[rid].get("severity"))
                     != (new_by[rid].get("when"), new_by[rid].get("then"), new_by[rid].get("kind"), new_by[rid].get("severity")))
    return added, removed, changed


def read_lock(project):
    """The rules as last accepted, or None when the project has never accepted a vocabulary."""
    from ..model.vocabulary import lock_path

    path = lock_path(project)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return list(json.load(f).get("rules") or [])
