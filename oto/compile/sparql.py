# -*- coding: utf-8 -*-
"""The SPARQL rendering of a competency question.

A question is written once, in the pattern language of `questions.json` (reason/questions.py), and
the engine runs it over the store. This module renders the same question as SPARQL over the RDF
the build writes (`graph.ttl`), so a reader with rdflib or a triple store asks what OTO asks. The
rendering is mechanical and the engine never runs it; a test keeps the two in step.

    node {var, type, where}   ->  ?var a <C> .           (a union, or a class with kinds: VALUES)
    optional [patterns]       ->  OPTIONAL { ... }
    edge [a, rel, b]          ->  ?a <rel> ?b .          (a union of relations: VALUES on the predicate)
    not_edge, not_node        ->  FILTER NOT EXISTS { ... }
    where {attr: {op: v}}     ->  ?var <attr> ?var_attr . FILTER(?var_attr op v)
    select var.label / .type / .<attr>  ->  OPTIONAL { ?var rdfs:label ?var_label } ...
    $NAME (a parameter)       ->  $NAME, for the caller to replace with the entity's IRI

Current facts only: every bound node is filtered to a status of `current`, as the engine does.
What the pattern language can say and SPARQL cannot read from the export is returned as a note:
`contains` on a list attribute (lists are RDF collections), and `$today`, which is rendered as the
date of the rendering.
"""
import datetime
import json
import re

from ..model import vocabulary as _vocab
from ..reason.match import BUILTIN_FIELDS, REFERENCE, resolve as _resolve_date, ISO_DATE
from . import rdf

#: A node's own fields, as the export writes them.
FIELD_PREDICATE = {"status": "status", "as_of": "asOf", "valid_from": "validFrom", "valid_to": "validTo",
                   "source_doc": "sourceDoc"}
OPERATORS = {"=": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
VAR_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _split(spec):
    return [x.strip() for x in str(spec or "").split("|") if x.strip()]


class Renderer:
    def __init__(self, vocabulary, terms, language=None, statuses=("current",), full_iris=False):
        self.vocabulary = vocabulary
        self.terms = terms
        self.language = language or _vocab.languages(vocabulary)[0]
        self.statuses = tuple(statuses)
        #: full `<iri>` instead of prefixed names: a SHACL-SPARQL constraint declares no prefixes
        self.full_iris = full_iris
        self.classes = vocabulary.get("classes") or {}
        self.properties = vocabulary.get("properties") or {}
        self.covers = _vocab.covers(self.classes)
        self.rel_covers = _vocab.relation_covers(self.properties)
        self.notes = []
        self._fresh = 0
        self.params = set()
        self._outer = set()

    # ---- names ----
    def prefixes(self):
        out = dict(self.terms.prefixes)
        out["id"] = self.terms.instances
        return out

    def var(self, name):
        """`?name` for a pattern variable, `$NAME` for a parameter (the caller substitutes)."""
        if name.startswith("$"):
            return name
        return "?" + name

    def fresh(self):
        self._fresh += 1
        return "?_%d" % self._fresh

    def cls(self, name):
        return "<%s>" % self.terms.iri(name) if self.full_iris else self.terms.curie(name)

    def rel(self, name):
        return "<%s>" % self.terms.iri(name) if self.full_iris else self.terms.curie(name)

    def field(self, name):
        pred = FIELD_PREDICATE[name]
        return "<%s>" % self.terms.temporal(pred) if self.full_iris else self.terms.temporal_curie(pred)

    def attribute_iri(self, name):
        return "<%s>" % self.terms.iri(name) if self.full_iris else self.terms.curie(name)

    def concept(self, scheme, key):
        name = "%s.%s" % (scheme, key)
        return "<%s>" % self.terms.iri(name, beside=scheme) if self.full_iris else self.terms.curie(name, beside=scheme)

    @property
    def rdfs_label(self):
        return "<%slabel>" % rdf.RDFS if self.full_iris else "rdfs:label"

    @property
    def xsd_date(self):
        return "<%sdate>" % rdf.XSD if self.full_iris else "xsd:date"

    # ---- values ----
    def literal(self, value, spec=None):
        """A where value as a SPARQL term, typed by the attribute's declaration when known."""
        kind = (spec or {}).get("type")
        if isinstance(kind, str) and kind.startswith("scheme:") and isinstance(value, str):
            return self.concept(kind[7:], value)
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return json.dumps(value)
        if isinstance(value, str):
            resolved = _resolve_date(value)
            if resolved != value:
                self.notes.append("`%s` is rendered as the date of the rendering (%s)" % (value, resolved))
            if ISO_DATE.match(resolved) and (kind == "date" or value != resolved):
                return '"%s"^^%s' % (resolved, self.xsd_date)
            return '"%s"' % rdf.escape(resolved)
        return '"%s"' % rdf.escape(json.dumps(value))

    # ---- patterns ----
    def node_pattern(self, pattern, var_types, lines):
        var = self.var(pattern["node"])
        kinds = _split(pattern.get("type"))
        if kinds:
            var_types[pattern["node"].lstrip("$")] = kinds
            expanded = []
            for kind in kinds:
                expanded += [k for k in sorted(self.covers.get(kind, {kind})) if k not in expanded]
            if len(expanded) == 1:
                lines.append("%s a %s ." % (var, self.cls(expanded[0])))
            else:
                t = self.fresh()
                lines.append("%s a %s . VALUES %s { %s }" % (var, t, t, " ".join(self.cls(k) for k in expanded)))
        else:
            lines.append("%s a %s ." % (var, self.fresh()))
        declared = {}
        for kind in var_types.get(pattern["node"].lstrip("$"), []):
            declared.update(_vocab.declared_attributes(self.vocabulary, kind))
        for name, condition in (pattern.get("where") or {}).items():
            conditions = condition if isinstance(condition, dict) else {"=": condition}
            spec = declared.get(name)
            if name in BUILTIN_FIELDS and not spec:
                if name == "label":
                    predicate = self.rdfs_label
                elif name == "type":
                    predicate = "a"
                elif name == "id":
                    predicate = None
                else:
                    predicate = self.field(name)
            else:
                predicate = self.attribute_iri(name)
            value_var = "%s_%s" % (var.replace("$", "?"), name)
            if predicate is None:
                lines.append("BIND(STRAFTER(STR(%s), \"id/\") AS %s)" % (var, value_var))
            elif predicate == "a":
                lines.append("%s a %s ." % (var, value_var))
            else:
                lines.append("%s %s %s ." % (var, predicate, value_var))
            for op, expected in conditions.items():
                if op == "exists":
                    # the triple above would already require the value: rewrite it as a test
                    lines.pop()
                    lines.append("FILTER %sEXISTS { %s %s %s }" % ("" if expected else "NOT ", var, predicate, value_var))
                    continue
                if isinstance(expected, str) and REFERENCE.search(expected) \
                        and all(m.group(1) in self._outer or m.group(1) in self.params for m in REFERENCE.finditer(expected)):
                    parts = []                                  # the string as CONCAT of text and references
                    last = 0
                    for m in REFERENCE.finditer(expected):
                        if m.start() > last:
                            parts.append('"%s"' % rdf.escape(expected[last:m.start()]))
                        other, field = m.group(1), m.group(2)
                        subject = self.var("$" + other) if other in self.params else "?" + other
                        if field:
                            ref = "?%s_%s" % (other, field)
                            lines.append("%s %s %s ." % (subject, self.attribute_iri(field), ref))
                            parts.append("STR(%s)" % ref)
                        else:
                            parts.append(subject)
                        last = m.end()
                    if last < len(expected):
                        parts.append('"%s"' % rdf.escape(expected[last:]))
                    ref = parts[0] if len(parts) == 1 else "CONCAT(%s)" % ", ".join(parts)
                    if predicate is None:                       # the id itself: compare the nodes
                        lines.pop()
                        value_var = var
                    if op in OPERATORS:
                        lines.append("FILTER(%s %s %s)" % (value_var, OPERATORS[op], ref))
                    elif op == "contains":
                        lines.append("FILTER(CONTAINS(STR(%s), %s))" % (value_var, ref if len(parts) > 1 else "STR(%s)" % ref))
                    continue
                if op in OPERATORS:
                    if predicate == "a":
                        lines.append("FILTER(%s %s %s)" % (value_var, OPERATORS[op], self.cls(str(expected))))
                    else:
                        lines.append("FILTER(%s %s %s)" % (value_var, OPERATORS[op], self.literal(expected, spec)))
                elif op == "in":
                    values = expected if isinstance(expected, list) else [expected]
                    lines.append("FILTER(%s IN (%s))" % (value_var, ", ".join(self.literal(v, spec) for v in values)))
                elif op == "contains":
                    if spec and str(spec.get("type")) == "list":
                        self.notes.append("`contains` on the list attribute %s is not rendered: a list is an RDF collection" % name)
                        lines.append("# contains on %s: not rendered" % name)
                    else:
                        lines.append("FILTER(CONTAINS(STR(%s), %s))" % (value_var, self.literal(str(expected))))

    def edge_pattern(self, spec, lines):
        src, rel, dst = spec
        s = self.var(src) if src != "*" else self.fresh()
        o = self.var(dst) if dst != "*" else self.fresh()
        rels = []
        for one in _split(rel):
            rels += [r for r in sorted(self.rel_covers.get(one, {one})) if r not in rels]
        if not rels:
            lines.append("%s %s %s ." % (s, self.fresh(), o))
        elif len(rels) == 1:
            lines.append("%s %s %s ." % (s, self.rel(rels[0]), o))
        else:
            p = self.fresh()
            lines.append("%s %s %s . VALUES %s { %s }" % (s, p, o, p, " ".join(self.rel(r) for r in rels)))

    def patterns(self, when, var_types, lines):
        for pattern in when:
            if "node" in pattern:
                self.node_pattern(pattern, var_types, lines)
            elif "edge" in pattern:
                self.edge_pattern(pattern["edge"], lines)
            elif "not_edge" in pattern:
                inner = []
                self.edge_pattern(pattern["not_edge"], inner)
                lines.append("FILTER NOT EXISTS { %s }" % " ".join(inner))
            elif "not_node" in pattern:
                inner = []
                self.node_pattern({"node": "_absent", "type": pattern.get("type"), "where": pattern.get("where")}, dict(var_types), inner)
                lines.append("FILTER NOT EXISTS { %s }" % " ".join(inner))
            elif "optional" in pattern:
                inner = []
                self.patterns(pattern["optional"], var_types, inner)
                # a variable bound only here is filtered to current facts here, where it is bound,
                # and what the selection reads from it is read here too
                own = [v for v in self.bound(pattern["optional"], {}) if v not in self._outer]
                self.current_only(own, inner)
                for v in own:
                    inner += self._selected.pop(v, [])
                lines.append("OPTIONAL { %s }" % " ".join(inner))

    def current_only(self, variables, lines):
        allowed = ", ".join('"%s"' % x for x in self.statuses)
        for name in variables:
            v = self.var(name)
            s = "%s_status" % v.replace("$", "?")
            lines.append("FILTER NOT EXISTS { %s %s %s . FILTER(%s NOT IN (%s)) }" % (v, self.field("status"), s, s, allowed))

    def _collect_types(self, when, var_types):
        for pattern in when:
            if isinstance(pattern.get("node"), str) and pattern.get("type"):
                var_types[pattern["node"].lstrip("$")] = _split(pattern["type"])
            if isinstance(pattern.get("optional"), list):
                self._collect_types(pattern["optional"], var_types)

    def bound(self, when, params):
        out = []
        for pattern in when:
            if isinstance(pattern.get("node"), str):
                out.append(pattern["node"])
            spec = pattern.get("edge")
            if isinstance(spec, list) and len(spec) == 3:
                out += [v for v in (spec[0], spec[2]) if v != "*"]
        seen = []
        for v in out:
            if v not in seen:
                seen.append(v)
        return seen

    # ---- the query ----
    def render(self, question, params=None):
        """The SPARQL of a question's `ask` (or of a body passed as `question`), with `$NAME` left
        for the caller. Returns the query text; what could not be rendered is in `self.notes`."""
        declared = params if params is not None else (question.get("params") or {})
        self.params = set(declared)
        ask = question.get("ask") or question
        when = ask.get("when") or []
        var_types = {name: _split(spec.get("type")) for name, spec in declared.items() if isinstance(spec, dict)}
        lines = []
        bound = self.bound(when, declared)
        self._outer = set(bound) | {"$" + name for name in declared} | set(declared)
        # what the selection reads from each variable, to be placed where the variable is bound
        all_types = dict(var_types)
        self._collect_types(when, all_types)
        projection, self._selected = [], {}
        for item in ask.get("select") or []:
            var, _dot, field = item.partition(".")
            v = self.var(var)
            if not field:
                projection.append(v)
                continue
            out = "%s_%s" % (v.replace("$", "?"), field)
            projection.append(out)
            key = var.lstrip("$")
            spec = {}
            for kind in all_types.get(key, []):
                spec.update(_vocab.declared_attributes(self.vocabulary, kind))
            if field in spec:
                line = "OPTIONAL { %s %s %s }" % (v, self.attribute_iri(field), out)
            elif field == "label":
                line = "OPTIONAL { %s %s %s }" % (v, self.rdfs_label, out)
            elif field == "type":
                line = "%s a %s ." % (v, out)
            elif field == "id":
                line = "BIND(STRAFTER(STR(%s), \"id/\") AS %s)" % (v, out)
            elif field in FIELD_PREDICATE:
                line = "OPTIONAL { %s %s %s }" % (v, self.field(field), out)
            else:
                line = "OPTIONAL { %s %s %s }" % (v, self.attribute_iri(field), out)
            self._selected.setdefault(var, []).append(line)
        self.patterns(when, var_types, lines)
        self.current_only(bound, lines)
        for var in list(self._selected):
            lines += self._selected.pop(var)
        head = "\n".join("PREFIX %s: <%s>" % (p, iri) for p, iri in sorted(self.prefixes().items()))
        head += "\nPREFIX rdfs: <%s>\nPREFIX xsd: <%s>" % (rdf.RDFS, rdf.XSD)
        select = "SELECT DISTINCT %s" % " ".join(projection) if projection else "SELECT *"
        return "%s\n%s WHERE {\n  %s\n}" % (head, select, "\n  ".join(lines))


def policy_constraint(rule, vocabulary, terms):
    """A policy rule as a SHACL-SPARQL constraint: (target classes, the SELECT with `$this` as the
    focus node) or None when the rule's first pattern binds no class. A policy sees intended facts
    too, as the engine's does."""
    from ..reason.match import BELIEVED_OR_INTENDED
    when = list(rule.get("when") or [])
    first = next((p for p in when if isinstance(p, dict) and "node" in p and p.get("type")), None)
    if first is None:
        return None
    focus = first["node"]

    def swap(value):
        return "$this" if value == focus else value

    renamed = []
    for pattern in when:
        new = dict(pattern)
        if isinstance(new.get("node"), str):
            new["node"] = swap(new["node"])
        for key in ("edge", "not_edge"):
            if isinstance(new.get(key), list):
                new[key] = [swap(v) for v in new[key]]
        renamed.append(new)
    renderer = Renderer(vocabulary, terms, statuses=BELIEVED_OR_INTENDED, full_iris=True)
    query = renderer.render({"ask": {"when": renamed, "select": ["$this"]}}, params={"this": {"type": first["type"]}})
    body = query.split(" WHERE {", 1)[1]
    return _split(first["type"]), "SELECT $this WHERE {" + body


def questions_yaml(questions, vocabulary, terms, name, language=None):
    """`questions.yaml`: every question with its SPARQL, in the shape a reader already runs."""
    renderer = Renderer(vocabulary, terms, language)
    lines = ["# Competency questions of the %s vocabulary, rendered as SPARQL over graph.ttl." % name,
             "# Written by `oto build` from questions.json; the engine runs the pattern form and never this.",
             "# Replace $NAME with the entity's IRI (<%s...>) before running a parameterised question." % terms.instances,
             "# graph.ttl holds asserted facts; derived facts (derived.json) are not in it.",
             "",
             "ontology: %s" % terms.project.rstrip("#/"),
             "questions:"]
    for qid, q in questions.items():
        renderer.notes, renderer._fresh = [], 0
        query = renderer.render(q)
        lines.append("  %s:" % qid)
        lines.append("    who: %s" % json.dumps(q.get("who") or "anyone"))
        lines.append("    question: %s" % json.dumps(q.get("question") or ""))
        if q.get("why"):
            lines.append("    why: %s" % json.dumps(q["why"]))
        if q.get("params"):
            lines.append("    params: %s" % json.dumps({k: v.get("type") for k, v in q["params"].items()}))
        lines.append("    gate: %s" % json.dumps(q.get("gate", "non_empty")))
        lines.append("    answer: |")
        lines += ["      " + line for line in query.splitlines()]
        from ..reason.questions import _gap_bodies
        for index, body in enumerate(_gap_bodies(q)):
            renderer._fresh = 0
            gaps = renderer.render({"ask": {"when": body.get("when") or [], "select": []}}, params=q.get("params") or {})
            suffix = "" if index == 0 else "_%d" % (index + 1)
            lines.append("    gaps%s: |" % suffix)
            lines += ["      " + line for line in gaps.splitlines()]
            lines.append("    gaps%s_say: %s" % (suffix, json.dumps(body.get("say") or "")))
        if renderer.notes:
            lines.append("    notes: %s" % json.dumps(sorted(set(renderer.notes))))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
