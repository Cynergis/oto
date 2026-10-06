# -*- coding: utf-8 -*-
"""Pattern matching over the graph. Deterministic: every iteration is over sorted ids."""
import datetime
import os
import re

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TODAY_REF = re.compile(r"^\$today(?:-(\d+)d)?$")
#: Fields of the node itself a `where` condition may name, beside the declared attributes.
BUILTIN_FIELDS = ("status", "as_of", "valid_from", "valid_to", "source_doc", "type", "label", "id")
#: What a derivation sees. A policy also sees `intended` facts, so it can flag a plan gone stale.
BELIEVED = ("current",)
BELIEVED_OR_INTENDED = ("current", "intended")


def today():
    """Today's date, or OTO_TODAY when set (tests, and a build that must be reproducible)."""
    return (os.environ.get("OTO_TODAY") or "").strip() or datetime.date.today().isoformat()


def resolve(expected):
    """`$today` and `$today-<n>d` as ISO dates; anything else as is."""
    if isinstance(expected, str):
        m = TODAY_REF.match(expected)
        if m:
            base = datetime.date.fromisoformat(today())
            return (base - datetime.timedelta(days=int(m.group(1) or 0))).isoformat()
    return expected


class Graph:
    """What a rule can see: the nodes whose status is in `statuses` (current by default), their
    edges (asserted and derived so far), attributes."""

    def __init__(self, nodes, edges, derived_attributes=None, statuses=BELIEVED, covers=None, declared=None):
        self.nodes = {n["id"]: n for n in nodes if n.get("id") and n.get("status", "current") in statuses}
        #: class -> the classes a pattern naming it matches: itself and the kinds of it (model/vocabulary.py)
        self.covers = covers or {}
        #: class -> the attribute names it declares (inherited ones included): a declared name shadows
        #: the node's own field of that name even when the node carries no value for it
        self.declared = declared or {}
        self.edges = []
        self.out = {}
        self.inc = {}
        self.keys = set()
        self.derived_attributes = derived_attributes or {}          # node id -> {name: value}
        for edge in edges:
            self.add_edge(edge)

    def add_edge(self, edge):
        key = (edge.get("from"), edge.get("rel"), edge.get("to"))
        if key in self.keys or edge.get("status") == "superseded":
            return False
        if key[0] not in self.nodes or key[2] not in self.nodes:
            return False
        self.keys.add(key)
        self.edges.append(edge)
        self.out.setdefault(key[0], []).append(edge)
        self.inc.setdefault(key[2], []).append(edge)
        return True

    def attribute(self, nid, name):
        """A declared attribute of the node, asserted or derived; else one of the node's own fields.
        An attribute the vocabulary declares under a built-in name (`label`, `status`) is the
        declared term: it wins when the node carries it, and is absent, not the node's field, when
        it does not. Without the declarations, a carried value wins and the field is the fallback."""
        node = self.nodes.get(nid) or {}
        value = (node.get("attributes") or {}).get(name)
        if value is None:
            value = self.derived_attributes.get(nid, {}).get(name)
        if value is None and name in BUILTIN_FIELDS and name not in self.declared.get(node.get("type"), ()):
            return node.get(name, "current" if name == "status" else None)
        return value


def _split(spec):
    return [x.strip() for x in str(spec or "").split("|") if x.strip()]


REFERENCE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?")


def _reference(expected, graph, bindings):
    """A `where` value may name a bound variable: `$REPORT` is its id, `$FIELD.fieldId` one of its
    attributes; inside a longer string (`fields.$FIELD.fieldId.`) the reference is spliced in as
    text. Anything else is the value itself."""
    if not (isinstance(expected, str) and "$" in expected and bindings is not None):
        return expected

    def value(match):
        nid = bindings.get(match.group(1))
        if nid is None:
            return None
        return graph.attribute(nid, match.group(2)) if match.group(2) else nid

    whole = REFERENCE.fullmatch(expected)
    if whole:
        found = value(whole)
        return expected if found is None and bindings.get(whole.group(1)) is None else found
    def splice(m):
        if bindings.get(m.group(1)) is None:        # not a binding (`$today-30d` is a date): left as written
            return m.group(0)
        found = value(m)
        return "" if found is None else str(found)
    return REFERENCE.sub(splice, expected)


def compare(op, value, expected):
    if op == "exists":
        return (value is not None and value != "" and value != []) == bool(expected)
    if value is None:
        return False
    expected = resolve(expected)
    if op == "=":
        return value == expected
    if op == "!=":
        return value != expected
    if op == "in":
        return value in (expected if isinstance(expected, list) else [expected])
    if op == "contains":
        return expected in value if isinstance(value, (list, str)) else False
    if op in ("<", "<=", ">", ">="):
        try:
            if isinstance(value, str) and isinstance(expected, str) and ISO_DATE.match(value) and ISO_DATE.match(expected):
                a, b = value, expected
            else:
                a, b = float(value), float(expected)
        except (TypeError, ValueError):
            return False
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    return False


def node_fits(graph, nid, pattern, bindings=None):
    node = graph.nodes.get(nid)
    if node is None:
        return False
    kinds = _split(pattern.get("type"))
    if kinds and not any(node.get("type") in graph.covers.get(kind, {kind}) for kind in kinds):
        return False
    for name, condition in (pattern.get("where") or {}).items():
        value = graph.attribute(nid, name)
        conditions = condition if isinstance(condition, dict) else {"=": condition}
        for op, expected in conditions.items():
            if not compare(op, value, _reference(expected, graph, bindings)):
                return False
    return True


def _edges(graph, bindings, spec):
    """Edges matching [from, rel, to] under the bindings, as (edge, new bindings)."""
    src, rel, dst = spec
    rels = _split(rel)
    if src != "*" and src in bindings:
        candidates = graph.out.get(bindings[src], [])
    elif dst != "*" and dst in bindings:
        candidates = graph.inc.get(bindings[dst], [])
    else:
        candidates = graph.edges
    for edge in sorted(candidates, key=lambda e: (e["from"], e["rel"], e["to"])):
        if rels and edge["rel"] not in rels:
            continue
        if src != "*" and src in bindings and edge["from"] != bindings[src]:
            continue
        if dst != "*" and dst in bindings and edge["to"] != bindings[dst]:
            continue
        new = dict(bindings)
        if src != "*":
            new[src] = edge["from"]
        if dst != "*":
            new[dst] = edge["to"]
        yield edge, new


def matches(graph, when, bindings=None):
    """Every binding that satisfies all patterns, with the edges it used, in a stable order.
    `bindings` pre-binds variables (a question's parameters); a pattern naming one must fit it.
    An `optional` block (a list of patterns) extends a binding when it matches and keeps the
    binding, its variables unbound, when it does not: a left join, for the facts a question
    reports when they are there and does not require."""
    results = [(dict(bindings or {}), [])]
    for pattern in when:
        next_results = []
        for bindings, used in results:
            if "node" in pattern:
                var = pattern["node"]
                if var in bindings:
                    if node_fits(graph, bindings[var], pattern, bindings):
                        next_results.append((bindings, used))
                    continue
                for nid in sorted(graph.nodes):
                    if node_fits(graph, nid, pattern, bindings):
                        new = dict(bindings)
                        new[var] = nid
                        next_results.append((new, used))
            elif "edge" in pattern:
                for edge, new in _edges(graph, bindings, pattern["edge"]):
                    next_results.append((new, used + [edge]))
            elif "not_edge" in pattern:
                if not any(True for _ in _edges(graph, bindings, pattern["not_edge"])):
                    next_results.append((bindings, used))
            elif "not_node" in pattern:
                if not any(node_fits(graph, nid, {"type": pattern.get("type"), "where": pattern.get("where")}, bindings)
                           for nid in graph.nodes):
                    next_results.append((bindings, used))
            elif "optional" in pattern:
                extended = [(b, used + u) for b, u in matches(graph, pattern["optional"], bindings)]
                next_results += extended if extended else [(bindings, used)]
        results = next_results
        if not results:
            break
    return results
