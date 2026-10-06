# -*- coding: utf-8 -*-
"""Read a real ontology, OWL, RDFS and SKOS in any RDF syntax, into the vocabulary's form.

Behind the `rdf` extra (rdflib, BSD-3-Clause): the compile path never needs it, an import does.
What the vocabulary can hold is read: classes with their parents, object properties with unions,
inverses and parents, datatype properties as attributes of their domain classes, SKOS labels and
notes on every term (`rdfs:comment` as the definition when there is no `skos:definition`), concept
schemes, the recorded reasoning (`meta:` annotations), and where each term lives, so its IRI is
kept. What it cannot hold is reported, never dropped in silence: a parent outside the file, a
restriction, a cardinality, a property chain, a name two namespaces both declare.

    classes, properties, notes = read(paths)
    read.attributes, read.schemes, read.namespaces, read.rationale
"""
import os
import re

from . import vocabulary as _vocab

XSD = "http://www.w3.org/2001/XMLSchema#"
XSD_TO_TYPE = {"string": "string", "decimal": "number", "double": "number", "float": "number", "integer": "integer",
               "int": "integer", "long": "integer", "boolean": "boolean", "date": "date"}
META = "https://cynergis.ai/ont/meta#"
FORMATS = {".ttl": "turtle", ".rdf": "xml", ".owl": "xml", ".xml": "xml", ".jsonld": "json-ld", ".nt": "nt", ".n3": "n3"}
ENUM_COMMENT = re.compile(r"^(.*?)\s*\(one of: ([^)]*)\)\s*$")
SCHEME_COMMENT = re.compile(r"^(.*?)\s*\(a concept of ([\w-]+)\)\s*$")
RDF_LIST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#List"


def available():
    try:
        import rdflib  # noqa: F401
        return True
    except ImportError:
        return False


def _ns(iri):
    """(namespace, local name): the part up to the last # or /."""
    text = str(iri)
    cut = max(text.rfind("#"), text.rfind("/")) + 1
    return text[:cut], text[cut:]


def read(paths):
    """(classes, properties, notes) from one or more RDF files; the rest on `read.<attribute>`."""
    from rdflib import Graph, URIRef, BNode
    from rdflib.collection import Collection
    from rdflib.namespace import OWL, RDF, RDFS, SKOS

    paths = [paths] if isinstance(paths, str) else list(paths)
    g = Graph()
    for path in paths:
        fmt = FORMATS.get(os.path.splitext(path)[1].lower())
        g.parse(path, format=fmt)
    notes = []
    prefixes = {str(ns): p for p, ns in g.namespaces() if p}

    # ---- the names: one per term, the second namespace to claim one is prefixed ----
    names, owner = {}, {}

    def name_of(iri):
        if iri in names:
            return names[iri]
        namespace, local = _ns(iri)
        name = local
        if name in owner and owner[name] != namespace:
            prefix = prefixes.get(namespace) or re.sub(r"[^A-Za-z0-9]+", "_", namespace.rstrip("#/").rsplit("/", 1)[-1])
            name = "%s_%s" % (prefix, local)
            notes.append("%s is declared in two namespaces; the one in <%s> is imported as %r" % (local, namespace, name))
        names[iri], owner[name] = name, namespace
        return name

    def texts(subject, predicate):
        out = {}
        for value in g.objects(subject, predicate):
            if getattr(value, "language", None) or isinstance(value.toPython(), str):
                out[value.language or _vocab.DEFAULT_LANGUAGE] = str(value)
        return out

    def as_text(found):
        if not found:
            return None
        return found[_vocab.DEFAULT_LANGUAGE] if list(found) == [_vocab.DEFAULT_LANGUAGE] else found

    def annotations(subject, name):
        spec = {}
        definition = as_text(texts(subject, SKOS.definition)) or as_text(texts(subject, RDFS.comment))
        if definition:
            spec["definition"] = definition
        label = as_text(texts(subject, SKOS.prefLabel)) or as_text(texts(subject, RDFS.label))
        if label and label != _vocab.name_as_words(name):
            spec["label"] = label
        alternatives = {}
        for value in g.objects(subject, SKOS.altLabel):
            alternatives.setdefault(value.language or _vocab.DEFAULT_LANGUAGE, []).append(str(value))
        if alternatives:
            spec["alt_labels"] = alternatives[_vocab.DEFAULT_LANGUAGE] if list(alternatives) == [_vocab.DEFAULT_LANGUAGE] else alternatives
        for key, predicate in (("scope_note", SKOS.scopeNote), ("example", SKOS.example)):
            value = as_text(texts(subject, predicate))
            if value:
                spec[key] = value
        return spec

    def reasoning(subject):
        entry = {}
        for key, local in (("question", "question"), ("why", "rationale"), ("alternatives", "alternatives"), ("validated_by", "validatedBy")):
            value = g.value(subject, URIRef(META + local))
            if value is not None:
                entry[key] = str(value)
        return entry

    class_iris = sorted({s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
                        | {s for s in g.subjects(RDF.type, RDFS.Class) if isinstance(s, URIRef)}, key=str)
    object_iris = sorted((s for s in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(s, URIRef)), key=str)
    data_iris = sorted((s for s in g.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(s, URIRef)), key=str)
    for iri in class_iris + object_iris + data_iris:
        name_of(iri)

    def classes_of(node, what, term):
        """The class names a domain or range gives: one class, or a union; others are reported."""
        if node is None:
            return None
        members = list(Collection(g, g.value(node, OWL.unionOf))) if isinstance(node, BNode) and g.value(node, OWL.unionOf) else [node]
        kept = []
        for member in members:
            if member in class_iris:
                kept.append(name_of(member))
            elif isinstance(member, BNode):
                notes.append("%s %r: a %s that is a restriction or an anonymous class is not read" % (what, term, "domain" if what == "relation" else "range"))
            else:
                notes.append("%s %r names <%s> in its %s, which the file does not declare; left out" % (what, term, member, "domain/range"))
        return "|".join(kept) if kept else None

    classes, properties, attributes, schemes, rationale = {}, {}, {}, {}, {"classes": {}, "properties": {}}
    for iri in class_iris:
        name = name_of(iri)
        spec = dict({"definition": ""}, **annotations(iri, name))
        parents = []
        for parent in g.objects(iri, RDFS.subClassOf):
            if parent in class_iris:
                parents.append(name_of(parent))
            elif isinstance(parent, BNode):
                notes.append("class %r is a subclass of a restriction, which is not read" % name)
            else:
                notes.append("class %r is a kind of <%s>, which the file does not declare; the parent is left out" % (name, parent))
        if parents:
            spec["subclass_of"] = parents
        classes[name] = spec
        why = reasoning(iri)
        if why:
            rationale["classes"][name] = why

    def attribute_specs(iri, name, typed):
        """An attribute on each of its domain classes. With several, the export writes one
        definition per class, `Class: meaning`; an enum's values or a scheme's name sit in the text."""
        domain = classes_of(g.value(iri, RDFS.domain), "attribute", name)
        if not domain:
            notes.append("%r has no domain the file declares; an attribute belongs to a class, so it is skipped" % name)
            return
        spec = annotations(iri, name)
        definitions = texts(iri, SKOS.definition) or texts(iri, RDFS.comment)
        holders = domain.split("|")
        for kind in holders:
            own = {}
            for lang, text in definitions.items():
                for piece in [text] if len(holders) == 1 else [x for x in g.objects(iri, SKOS.definition) if x.language in (lang, None)] and [str(x) for x in g.objects(iri, SKOS.definition) if (x.language or _vocab.DEFAULT_LANGUAGE) == lang]:
                    if len(holders) > 1 and not piece.startswith(kind + ": "):
                        continue
                    own[lang] = piece[len(kind) + 2:] if len(holders) > 1 else piece
            definition = as_text(own) or ""
            kind_type = typed
            if isinstance(definition, str):
                enum, of = ENUM_COMMENT.match(definition), SCHEME_COMMENT.match(definition)
                if enum:
                    kind_type, definition = "enum:" + enum.group(2), enum.group(1)
                elif of:
                    kind_type, definition = "scheme:" + of.group(2), of.group(1)
            attributes.setdefault(kind, {})[name] = dict({"type": kind_type, "definition": definition},
                                                         **{k: v for k, v in spec.items() if k != "definition"})

    inverse_only = {}
    for iri in object_iris:
        name = name_of(iri)
        rng_node = g.value(iri, RDFS.range)
        if rng_node == URIRef(RDF_LIST):                    # a list attribute, written as a collection
            attribute_specs(iri, name, "list")
            continue
        if rng_node == SKOS.Concept or (isinstance(rng_node, BNode) and g.value(rng_node, OWL.onProperty) == SKOS.inScheme):
            scheme = g.value(rng_node, OWL.hasValue) if isinstance(rng_node, BNode) else None
            attribute_specs(iri, name, "scheme:" + name_of(scheme) if scheme is not None else "string")
            continue
        domain = classes_of(g.value(iri, RDFS.domain), "relation", name)
        rng = classes_of(rng_node, "relation", name)
        inverse = g.value(iri, OWL.inverseOf)
        if not domain and not rng and inverse is not None:    # the other side of a relation: its label only
            inverse_only[name] = as_text(texts(iri, SKOS.prefLabel))
            continue
        spec = {}
        if domain:
            spec["domain"] = domain
        else:
            notes.append("relation %r has no domain the file declares; it applies to any class" % name)
        if rng:
            spec["range"] = rng
        if inverse is not None:
            spec["inverse"] = name_of(inverse) if inverse in object_iris else _ns(inverse)[1]
        for parent in g.objects(iri, RDFS.subPropertyOf):
            if parent in object_iris:
                spec["subproperty_of"] = name_of(parent)
            else:
                notes.append("relation %r specialises <%s>, which the file does not declare; left out" % (name, parent))
        spec.update(annotations(iri, name))
        spec.setdefault("definition", "")
        properties[name] = spec
        why = reasoning(iri)
        if why:
            rationale["properties"][name] = why
    # an inverse declared only as the other side of a relation carries that relation's inverse label
    for name, spec in properties.items():
        written = inverse_only.get(spec.get("inverse"))
        if written and written != _vocab.name_as_words(spec["inverse"]):
            spec["inverse_label"] = written

    for iri in data_iris:
        name = name_of(iri)
        rng = g.value(iri, RDFS.range)
        typed = XSD_TO_TYPE.get(_ns(rng)[1], "string") if isinstance(rng, URIRef) and str(rng).startswith(XSD) else "string"
        if isinstance(rng, URIRef) and str(rng).startswith(XSD) and _ns(rng)[1] not in XSD_TO_TYPE:
            notes.append("attribute %r has range xsd:%s, read as string" % (name, _ns(rng)[1]))
        attribute_specs(iri, name, typed)

    for scheme_iri in sorted((s for s in g.subjects(RDF.type, SKOS.ConceptScheme) if isinstance(s, URIRef)), key=str):
        name = name_of(scheme_iri)
        scheme = dict({"definition": ""}, **annotations(scheme_iri, name))
        concepts = {}
        for concept in sorted(g.subjects(SKOS.inScheme, scheme_iri), key=str):
            local = _ns(concept)[1]
            key = local[len(name) + 1:] if local.startswith(name + ".") else local
            spec = annotations(concept, key)
            broader = g.value(concept, SKOS.broader)
            if broader is not None:
                parent = _ns(broader)[1]
                spec["broader"] = parent[len(name) + 1:] if parent.startswith(name + ".") else parent
            concepts[key] = spec
        if concepts:
            scheme["concepts"] = concepts
            schemes[name] = scheme
        else:
            notes.append("concept scheme %r has no concepts in the file; skipped" % name)
    for restriction in g.subjects(RDF.type, OWL.Restriction):
        if g.value(restriction, OWL.onProperty) != SKOS.inScheme:
            notes.append("a restriction on <%s> is not read: the vocabulary holds domains, ranges and kinds, not restrictions"
                         % g.value(restriction, OWL.onProperty))
            break
    for predicate, what in ((OWL.propertyChainAxiom, "a property chain"), (OWL.equivalentClass, "an equivalence"),
                            (OWL.disjointWith, "a disjointness")):
        if any(True for _ in g.subject_objects(predicate)):
            notes.append("%s is not read: the vocabulary cannot hold it" % what)

    # ---- shapes: SHACL property shapes become min/max on a relation, required on an attribute, or
    # a class's requires; what the vocabulary cannot hold is noted ----
    SH = "http://www.w3.org/ns/shacl#"
    counts = {}                                                 # (class, term) -> (min, max)
    for shape in sorted(g.subjects(RDF.type, URIRef(SH + "NodeShape")), key=str):
        target = g.value(shape, URIRef(SH + "targetClass"))
        if target not in class_iris:
            notes.append("a node shape targets <%s>, which is not a class of this vocabulary; skipped" % target)
            continue
        kind = name_of(target)
        for prop in g.objects(shape, URIRef(SH + "property")):
            path = g.value(prop, URIRef(SH + "path"))
            low = g.value(prop, URIRef(SH + "minCount"))
            high = g.value(prop, URIRef(SH + "maxCount"))
            if path not in names:
                notes.append("shape on %s constrains <%s>, which is not a term of this vocabulary; skipped" % (kind, path))
                continue
            others = [p for p in g.predicates(prop, None) if p not in (URIRef(SH + "path"), URIRef(SH + "minCount"), URIRef(SH + "maxCount"), URIRef(SH + "message"))]
            if others:
                notes.append("shape on %s %s: only minCount and maxCount are read; %s left out"
                             % (kind, name_of(path), ", ".join(sorted(_ns(p)[1] for p in others))))
            if low is None and high is None:
                continue
            counts[(kind, name_of(path))] = (int(low) if low is not None else 0, int(high) if high is not None else None)
    for (kind, term), (low, high) in sorted(counts.items()):
        if term in properties:
            domain = (properties[term].get("domain") or "").split("|")
            whole = all(counts.get((d, term)) == (low, high) for d in domain if d) and kind in domain
            if whole:                                           # every class of the domain agrees: the relation's own
                if low:
                    properties[term]["min"] = low
                if high is not None:
                    properties[term]["max"] = high
            elif low and high is None:
                classes[kind].setdefault("requires", [])
                if term not in classes[kind]["requires"]:
                    classes[kind]["requires"].append(term)
            else:
                notes.append("shape on %s %s (%s..%s) is not the same on every class of the relation's domain; "
                             "the vocabulary holds one cardinality per relation, so it is left out"
                             % (kind, term, low, "*" if high is None else high))
        elif term in (attributes.get(kind) or {}):
            if low:
                attributes[kind][term]["required"] = True
            if high is not None and high != 1:
                notes.append("shape on %s %s: maxCount %d on an attribute is not held; an attribute has one value" % (kind, term, high))
        else:
            notes.append("shape on %s constrains %s, which %s does not carry; skipped" % (kind, term, kind))

    # where each term lives, keyed by the file's prefix for its namespace, so the IRIs are kept
    namespaces, prefix_of = {}, {}

    def prefix_for(namespace):
        if namespace in prefix_of:
            return prefix_of[namespace]
        prefix = prefixes.get(namespace) or re.sub(r"[^A-Za-z0-9-]+", "-", namespace.rstrip("#/").rsplit("/", 1)[-1]).strip("-") or "ns"
        while prefix in namespaces:
            prefix += "-"
        prefix_of[namespace] = prefix
        namespaces[prefix] = {"iri": namespace, "terms": []}
        return prefix

    for iri, name in list(names.items()) + [(s, name_of(s)) for s in g.subjects(RDF.type, SKOS.ConceptScheme) if isinstance(s, URIRef)]:
        namespace, local = _ns(iri)
        entry = namespaces[prefix_for(namespace)]
        if name not in entry["terms"]:
            entry["terms"].append(name)
            if name != local:
                entry.setdefault("renamed", {})[name] = local

    read.attributes, read.schemes, read.namespaces, read.rationale = attributes, schemes, namespaces, rationale
    return classes, properties, sorted(set(notes))
