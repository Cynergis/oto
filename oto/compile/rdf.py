# -*- coding: utf-8 -*-
"""How a value is written as RDF. Shared by the stages that export triples and Turtle.

Nothing here knows the vocabulary: a caller says which datatype a value was declared with, or
leaves it to the value's own JSON type.
"""
import json
import re
from decimal import Decimal

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
#: Where a term's recorded reasoning is annotated: the vocabulary the report ontology uses too.
META = "https://cynergis.ai/ont/meta#"
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r"}


def escape(text):
    """A string as it sits between the quotes of an N-Triples or Turtle literal."""
    return "".join(_ESCAPES.get(ch, ch) for ch in str(text))


def ref(iri):
    return "<%s>" % iri


def literal(value, datatype=None, language=None):
    text = '"%s"' % escape(value)
    if language:
        return text + "@" + language
    return text + "^^<%s>" % datatype if datatype else text


def date(value):
    """A date field: typed when it is an ISO date, a plain literal otherwise."""
    return literal(value, XSD + "date") if ISO_DATE.match(str(value)) else literal(value)


def scalar(value, declared=None):
    """One JSON scalar as a literal: by the declared attribute type when it fits, else by its own type."""
    if isinstance(value, bool):
        return literal("true" if value else "false", XSD + "boolean")
    if isinstance(value, int):
        return literal(value, XSD + ("decimal" if declared == "number" else "integer"))
    if isinstance(value, float):
        return literal(format(Decimal(repr(value)), "f"), XSD + "decimal")
    if declared == "date":
        return date(value)
    return literal(value)


def as_json(value):
    """A structured value as one literal, canonically serialised so a rebuild writes the same bytes."""
    return literal(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")), RDF + "JSON")


def is_scalar(value):
    return isinstance(value, (str, int, float, bool))


# ---- Turtle, from the same triples ----
_LOCAL = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*[A-Za-z0-9_-]$|^[A-Za-z_]$")


def _compact(token, prefixes):
    """An `<iri>` or a typed literal's `^^<iri>` as `prefix:local` when a prefix covers it."""
    def short(iri):
        for prefix, namespace in prefixes.items():
            if iri.startswith(namespace) and _LOCAL.match(iri[len(namespace):]):
                return "%s:%s" % (prefix, iri[len(namespace):])
        return None
    if token.startswith("<") and token.endswith(">"):
        return short(token[1:-1]) or token
    if token.startswith('"') and "^^<" in token and token.endswith(">"):
        text, _, datatype = token.rpartition("^^<")
        return "%s^^%s" % (text, short(datatype[:-1]) or "<" + datatype)
    return token


def turtle(triples, prefixes):
    """The triples as readable Turtle: a block per subject, in the order they were written."""
    longest = {p: ns for p, ns in sorted(prefixes.items(), key=lambda kv: -len(kv[1]))}
    out = ["@prefix %s: <%s> ." % (prefix, namespace) for prefix, namespace in prefixes.items()] + [""]
    blocks, order = {}, []
    for s, p, o in triples:
        if s not in blocks:
            blocks[s], _ = [], order.append(s)
        predicate = "a" if p == "<%stype>" % RDF else _compact(p, longest)
        blocks[s].append("    %s %s" % (predicate, _compact(o, longest)))
    for s in order:
        out.append(_compact(s, longest) + "\n" + " ;\n".join(blocks[s]) + " .\n")
    return "\n".join(out)

