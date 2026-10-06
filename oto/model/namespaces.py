# -*- coding: utf-8 -*-
"""Where a term's IRI comes from.

A term belongs to the ontology that first declared it. An ontology says where its terms live with
`namespace` in its manifest; composing ontologies records, in the composed vocabulary, which terms
each one brought:

    "namespaces": {
      "oto-core": {"iri": "https://cynergis.ai/ont/oto-core#", "terms": ["Document", "cites"], "temporal": true},
      "auto-claims": {"iri": "https://cynergis.ai/ont/auto-claims#", "terms": ["Claim", "filed_under", "state"]}
    }

`terms` holds classes, relations, schemes and attribute names alike: the IRI of a name is its namespace plus
the name, whatever it names. When a name had to differ from the local name of its IRI (two
namespaces declaring `Field`, imported as `Field` and `rpt_Field`), `renamed` maps the name to the
local name, so the IRI is kept: `"renamed": {"rpt_Field": "Field"}`. `temporal` marks the one ontology the temporal vocabulary (asOf,
supersedes, ...) came from; those names are kept apart because a domain may declare a relation of
the same name. A term no entry lists is the project's own and lives under the project namespace:
a class the project declared itself, or a whole vocabulary designed in the project.

The section lives in `ontology.config.json` on purpose: the build reads the project and nothing
else, so two machines with different catalogs export the same IRIs.
"""
import re
from urllib.parse import quote

SECTION = "namespaces"
IRI_OK = re.compile(r"^https?://[^\s<>\"{}|\\^`]+[#/]$")
LOCAL_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*[A-Za-z0-9_-]$|^[A-Za-z_]$")
PREFIX_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
#: Prefixes the exports declare themselves.
RESERVED = ("rdf", "rdfs", "owl", "xsd")
#: Characters an IRI may carry unescaped; anything else in an id or a name is percent-encoded.
SAFE = "/:.-_~@!$&'()*+,;="


def iri_problem(iri, where):
    """Why `iri` cannot be a namespace, or None."""
    if not isinstance(iri, str) or not IRI_OK.match(iri):
        return "%s %r must be an http(s) IRI ending in # or /" % (where, iri)
    return None


def problems(config):
    """What is wrong with a vocabulary's `namespaces` section."""
    section = config.get(SECTION)
    if section is None:
        return []
    if not isinstance(section, dict):
        return ["namespaces must map an ontology name to {iri, terms}"]
    out, owner, temporal = [], {}, []
    for name, entry in section.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("terms", []), list):
            out.append("namespaces.%s must be {\"iri\": ..., \"terms\": [...]}" % name)
            continue
        problem = iri_problem(entry.get("iri"), "namespaces.%s.iri" % name)
        if problem:
            out.append(problem)
        for term in entry.get("terms") or []:
            if term in owner:
                out.append("namespaces: %r is listed under both %s and %s; a term has one IRI" % (term, owner[term], name))
            owner.setdefault(term, name)
        renamed = entry.get("renamed") or {}
        if not isinstance(renamed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in renamed.items()):
            out.append("namespaces.%s.renamed must map a name to the local name of its IRI" % name)
        elif set(renamed) - set(entry.get("terms") or []):
            out.append("namespaces.%s.renamed names terms the entry does not list: %s" % (name, ", ".join(sorted(set(renamed) - set(entry.get("terms") or [])))))
        if entry.get("temporal"):
            temporal.append(name)
    if len(temporal) > 1:
        out.append("namespaces: the temporal vocabulary comes from one ontology, not %s" % " and ".join(temporal))
    return out


def claim(record, name, iri, terms, temporal=False, renamed=None):
    """Record that ontology `name` brought `terms`. A term keeps the first ontology that claimed it."""
    taken = {term for entry in record.values() for term in entry["terms"]}
    entry = record.setdefault(name, {"iri": iri, "terms": []})
    for term in terms:
        if term not in taken:
            entry["terms"].append(term)
            taken.add(term)
            if (renamed or {}).get(term):
                entry.setdefault("renamed", {})[term] = renamed[term]
    if temporal and not any(e.get("temporal") for e in record.values()):
        entry["temporal"] = True
    return record


def inherit(record, declared):
    """Carry over what a composed vocabulary already records, first claim still winning."""
    for name, entry in (declared or {}).items():
        if isinstance(entry, dict) and entry.get("iri"):
            claim(record, name, entry["iri"], entry.get("terms") or [], bool(entry.get("temporal")), entry.get("renamed"))
    return record


def settled(record):
    """The section as it is written: ontologies that brought nothing are left out."""
    return {name: entry for name, entry in record.items() if entry["terms"] or entry.get("temporal")}


def own_terms(config):
    """Every name a vocabulary declares: classes, relations, attribute names."""
    names = list(config.get("classes") or {}) + list(config.get("properties") or {}) + list(config.get("schemes") or {})
    for declared in (config.get("attributes") or {}).values():
        names += list(declared or {})
    return names


class Terms:
    """The IRI of every term and every instance of one project."""

    def __init__(self, config, identity):
        base = identity["namespace"]
        self.instances = base + "id/"
        self.project = base + "ont/"
        self.project_prefix = identity["prefix"]
        self._namespace, self._temporal, self._local = {}, self.project, {}
        #: prefix -> namespace IRI, the project's first, then each ontology in the order declared.
        self.prefixes = {self.project_prefix: self.project}
        for name, entry in (config.get(SECTION) or {}).items():
            prefix = name if PREFIX_OK.match(name) else "ns"
            while prefix in self.prefixes or prefix in RESERVED:
                prefix += "-ont"
            self.prefixes[prefix] = entry["iri"]
            for term in entry.get("terms") or []:
                self._namespace.setdefault(term, entry["iri"])
                if (entry.get("renamed") or {}).get(term):
                    self._local[term] = entry["renamed"][term]
            if entry.get("temporal"):
                self._temporal = entry["iri"]
        self._prefix_of = {iri: prefix for prefix, iri in self.prefixes.items()}

    def iri(self, name, beside=None):
        """A class, relation or attribute. A name declared nowhere (an inverse) takes the namespace
        of the term it is declared `beside`."""
        home = self._namespace.get(name) or (self._namespace.get(beside, self.project) if beside else self.project)
        return home + quote(self._local.get(name, str(name)), safe=SAFE)

    def temporal(self, name):
        """A term of the temporal vocabulary (asOf, supersedes, ...)."""
        return self._temporal + quote(str(name), safe=SAFE)

    def instance(self, node_id):
        return self.instances + quote(str(node_id), safe=SAFE)

    def _short(self, namespace, name):
        if LOCAL_OK.match(str(name)):
            return "%s:%s" % (self._prefix_of[namespace], name)
        return "<%s%s>" % (namespace, quote(str(name), safe=SAFE))

    def curie(self, name, beside=None):
        """A term as Turtle writes it: `prefix:name`, or the full IRI when the name is no local name.
        A name declared nowhere (an inverse) takes the namespace of the term it is declared `beside`."""
        home = self._namespace.get(name) or (self._namespace.get(beside, self.project) if beside else self.project)
        return self._short(home, self._local.get(name, name))

    def temporal_curie(self, name):
        return self._short(self._temporal, name)
