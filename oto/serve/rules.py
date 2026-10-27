# -*- coding: utf-8 -*-
"""The rules as a person reads them (roadmap D2): each rule with its patterns in words, the classes,
relations and attributes it touches, and a lookup by class that honours inheritance, so a reader on
the Component page sees the rule declared on Asset. Carried in the graph payload as `rules` (so an
exported site has it) and served at /api/rules (`?class=<Name>` for the rules that apply to one).

A rule entry: id, kind (derive | policy), severity, why, validated_by (None when nobody has), answers
(the competency question a policy protects), when (one line per pattern), then (one line), scope
({variable: {classes, how}}: `declared` when the pattern names the class, `implied` when the relations
the variable takes part in narrow it), classes (sorted union of the scope), relations, attributes
(`Class.name`), every_node (a pattern binds a node of any class). `by_class` maps every declared class
to the ids of the rules that apply to it: named directly, named on an ancestor, or every_node;
`lineage` maps it to its ancestors, so a reader can say through which one a rule reaches it.
"""
import json
import os

from ..model import vocabulary as _vocab

NAME = "rules.json"
#: A node's own fields: conditions on them are not attribute reads.
FIELDS = ("status", "as_of", "valid_from", "valid_to", "source_doc")
OPERATORS = {"<": "<", ">": ">", "<=": "<=", ">=": ">=", "!=": "!=", "=": "=", "==": "="}


def load(project_root):
    """The rules declared beside the project, or none."""
    if not project_root:
        return []
    path = os.path.join(project_root, NAME)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    return [r for r in (rules or []) if isinstance(r, dict)]


def _split(spec):
    return [x.strip() for x in str(spec or "").split("|") if x.strip()]


def _value(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _condition(name, spec):
    if not isinstance(spec, dict):
        return "%s = %s" % (name, _value(spec))
    parts = []
    for op, v in spec.items():
        if op == "exists":
            parts.append("%s is %s" % (name, "present" if v else "absent"))
        elif op == "in":
            parts.append("%s in %s" % (name, _value(v)))
        elif op == "not_in":
            parts.append("%s not in %s" % (name, _value(v)))
        else:
            parts.append("%s %s %s" % (name, OPERATORS.get(op, op), _value(v)))
    return " and ".join(parts)


def _where(where):
    return " and ".join(_condition(k, v) for k, v in (where or {}).items())


def _types(spec):
    kinds = _split(spec)
    return " or ".join(kinds)


def _pattern(pattern):
    """One pattern as a line of words."""
    if "node" in pattern or "not_node" in pattern:
        var = pattern.get("node") or pattern.get("not_node")
        kinds, where = _types(pattern.get("type")), _where(pattern.get("where"))
        head = ("no " if "not_node" in pattern else "") + var
        text = head + (" is a " + kinds if kinds else ("" if where else " is any node"))
        return text + (" where " + where if where else "")
    if "edge" in pattern:
        return "edge %s %s %s" % tuple(pattern["edge"])
    if "not_edge" in pattern:
        return "no edge %s %s %s" % tuple(pattern["not_edge"])
    if "not" in pattern:
        return "nothing matches: " + "; ".join(_pattern(p) for p in pattern["not"] if isinstance(p, dict))
    return json.dumps(pattern, ensure_ascii=False)


def _then(then):
    then = then or {}
    if "flag" in then:
        return "flag: %s" % then["flag"]
    if "edge" in then:
        return "edge %s %s %s" % tuple(then["edge"])
    if "attribute" in then:
        var, name, value = then["attribute"]
        return "set %s.%s = %s" % (var, name, _value(value))
    return json.dumps(then, ensure_ascii=False)


def _scope(rule, properties):
    """{variable: {classes, how}}: a declared type, else the intersection of what the relations the
    variable takes part in allow (their union when they disagree), else nothing known."""
    declared, implied = {}, {}

    def note(var, kinds):
        if var == "*" or not kinds:
            return
        implied.setdefault(var, []).append(set(kinds))

    patterns = list(rule.get("when") or [])
    for pattern in list(patterns):
        if "not" in pattern and isinstance(pattern["not"], list):
            patterns.extend(p for p in pattern["not"] if isinstance(p, dict))
    for pattern in patterns:
        var = pattern.get("node") or pattern.get("not_node")
        if var and pattern.get("type"):
            declared[var] = _split(pattern["type"])
        for key in ("edge", "not_edge"):
            if key in pattern and len(pattern[key]) == 3:
                a, rel, b = pattern[key]
                for name in _split(rel):
                    spec = properties.get(name) or {}
                    note(a, _vocab._union(spec.get("domain")))
                    note(b, _vocab._union(spec.get("range")))
    then = rule.get("then") or {}
    if "edge" in then and len(then["edge"]) == 3:
        a, rel, b = then["edge"]
        spec = properties.get(rel) or {}
        note(a, _vocab._union(spec.get("domain")))
        note(b, _vocab._union(spec.get("range")))
    out = {}
    for var in sorted(set(declared) | set(implied)):
        if var in declared:
            out[var] = {"classes": sorted(declared[var]), "how": "declared"}
        else:
            sets = implied[var]
            meet = set.intersection(*sets)
            out[var] = {"classes": sorted(meet or set.union(*sets)), "how": "implied"}
    return out


def _attributes(rule, scope):
    out = set()

    def read(var, name):
        if name in FIELDS:
            return
        classes = (scope.get(var) or {}).get("classes") or []
        out.update("%s.%s" % (c, name) for c in classes) if classes else out.add(name)

    patterns = list(rule.get("when") or [])
    for pattern in list(patterns):
        if "not" in pattern and isinstance(pattern["not"], list):
            patterns.extend(p for p in pattern["not"] if isinstance(p, dict))
    for pattern in patterns:
        var = pattern.get("node") or pattern.get("not_node")
        if var:
            for name in (pattern.get("where") or {}):
                read(var, name)
    then = rule.get("then") or {}
    if "attribute" in then and len(then["attribute"]) == 3:
        read(then["attribute"][0], then["attribute"][1])
    return sorted(out)


def _relations(rule):
    out = set()
    patterns = list(rule.get("when") or [])
    for pattern in list(patterns):
        if "not" in pattern and isinstance(pattern["not"], list):
            patterns.extend(p for p in pattern["not"] if isinstance(p, dict))
    for pattern in patterns:
        for key in ("edge", "not_edge"):
            if key in pattern and len(pattern[key]) == 3:
                out.update(_split(pattern[key][1]))
    then = rule.get("then") or {}
    if "edge" in then and len(then["edge"]) == 3:
        out.add(then["edge"][1])
    return sorted(x for x in out if x != "*")


def _every_node(rule, scope):
    patterns = rule.get("when") or []
    return any(("node" in p) and p.get("node") not in scope for p in patterns if isinstance(p, dict))


def model(rules, vocabulary):
    """The rules projected for reading, with the lookup by class."""
    vocabulary = vocabulary or {}
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    out = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        scope = _scope(rule, properties)
        when = [_pattern(p) for p in (rule.get("when") or []) if isinstance(p, dict)]
        out.append({"id": rule.get("id"), "kind": rule.get("kind"), "severity": rule.get("severity"),
                    "why": rule.get("why") or None, "validated_by": rule.get("validated_by") or None,
                    "answers": rule.get("answers") or None, "when": when, "then": _then(rule.get("then")), "scope": scope,
                    "classes": sorted({c for s in scope.values() for c in s["classes"]}),
                    "relations": _relations(rule), "attributes": _attributes(rule, scope),
                    "every_node": _every_node(rule, scope)})
    by_class, lineage = {}, {}
    for name in classes:
        lineage[name] = list(_vocab.ancestors(classes, name))
        by_class[name] = [r["id"] for r in out if r["every_node"] or any(c in r["classes"] for c in [name] + lineage[name])]
    counts = {"rules": len(out), "derive": sum(1 for r in out if r["kind"] == "derive"),
              "policy": sum(1 for r in out if r["kind"] == "policy"), "confirmed": sum(1 for r in out if r["validated_by"])}
    return {"counts": counts, "rules": out, "by_class": by_class, "lineage": lineage}


def for_class(m, name):
    """The rules that apply to one class, each saying through which ancestor when not named directly;
    None for a class the model does not know."""
    if name not in (m.get("by_class") or {}):
        return None
    wanted = set(m["by_class"][name])
    lineage = (m.get("lineage") or {}).get(name) or []
    rules = []
    for rule in m["rules"]:
        if rule["id"] not in wanted:
            continue
        via = None if name in rule["classes"] or rule["every_node"] else next((a for a in lineage if a in rule["classes"]), None)
        rules.append(dict(rule, via=via))
    return {"class": name, "rules": rules}
