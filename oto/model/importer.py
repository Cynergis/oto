# -*- coding: utf-8 -*-
"""Bring a vocabulary in from outside: an ontology, a file OTO emitted, or a plain list.

A team that already owns a vocabulary should not retype it, and an agent that translates it by
hand should not be the only check on the translation. So the formats OTO can verify are read here,
and everything else stays a reading job for a person or an agent, whose result still lands in the
same config and passes the same gates.

Sources:

    --ontology a[,b]     shipped or exported ontologies, merged if more than one
    file.ttl, .rdf, .owl, .jsonld, .nt, .n3
                         any OWL, RDFS or SKOS ontology, read with rdflib (the `rdf` extra,
                         model/rdf_import.py): terms, labels, definitions, unions, parents, schemes
                         and the reasoning, each term keeping its IRI. Without the extra, a Turtle
                         file is read the way OTO writes one, one statement per line, and the terms
                         become the importing project's own
    file.csv             one row per term: kind, name, description, domain, range, inverse
                         (kind `attribute`: domain is the class, range is the type)
    file.json            the form of ontology.config.json: {"classes": {...}, "properties": {...}}

Every reader returns the vocabulary in the form `ontology.config.json` takes (model/vocabulary.py).

Nothing here writes a rationale. An imported class has no recorded reason yet, and inventing one
would be worse than none. `oto ontology rationale` reports the gap; the interview fills it.
"""
import csv
import json
import os
import re

CLASS_STMT = re.compile(r"^\s*[\w-]+:([\w-]+)\s+a\s+owl:Class\b(?P<rest>.*)$", re.S)
DATA_STMT = re.compile(r"^\s*[\w-]+:([\w-]+)\s+a\s+(?P<kind>owl:DatatypeProperty|rdf:Property)\b(?P<rest>.*)$", re.S)
XSD_TO_TYPE = {"xsd:string": "string", "xsd:decimal": "number", "xsd:double": "number", "xsd:float": "number",
               "xsd:integer": "integer", "xsd:int": "integer", "xsd:boolean": "boolean", "xsd:date": "date",
               "rdf:List": "list"}
ENUM_COMMENT = re.compile(r"^(.*?)\s*\(one of: ([^)]*)\)\s*$")
SCHEME_COMMENT = re.compile(r"^(.*?)\s*\(a concept of ([\w-]+)\)\s*$")
PROP_STMT = re.compile(r"^\s*[\w-]+:([\w-]+)\s+a\s+owl:ObjectProperty\b(?P<rest>.*)$", re.S)
SCHEME_STMT = re.compile(r"^\s*[\w-]+:([\w-]+)\s+a\s+skos:ConceptScheme\b(?P<rest>.*)$", re.S)
CONCEPT_STMT = re.compile(r"^\s*[\w-]+:([\w-]+)\.([\w-]+)\s+a\s+skos:Concept\b(?P<rest>.*)$", re.S)
#: An attribute whose values are a scheme's concepts, as the export writes its range.
IN_SCHEME = re.compile(r"owl:onProperty\s+skos:inScheme\s*;\s*owl:hasValue\s+[\w-]+:([\w-]+)")
#: A literal as the export writes one: escaped text, optionally tagged with a language.
LITERAL = r'"((?:[^"\\]|\\.)*)"(?:@([\w-]+))?'
#: A union of classes or datatypes, as the export writes one.
UNION = r"\[\s*a\s+(?:owl:Class|rdfs:Datatype)\s*;\s*owl:unionOf\s*\(([^)]*)\)\s*\]"
INVERSE = re.compile(r"owl:inverseOf\s+[\w-]+:([\w-]+)")
TEMPORAL_PREFIX = "# --- temporal"
#: The language a bare (untagged, or English) text is written in.
DEFAULT_LANGUAGE = "en"


def _target(rest, predicate):
    """What `rdfs:domain` or `rdfs:range` names: one class, or `A|B` from a union. None when the
    statement does not say."""
    union = re.search(predicate + r"\s+" + UNION, rest)
    if union:
        return "|".join(x.split(":")[-1] for x in union.group(1).split())
    one = re.search(predicate + r"\s+[\w-]+:([\w-]+)", rest)
    return one.group(1) if one else None


def _unescape(text):
    return re.sub(r'\\([\\"nr])', lambda m: {"n": "\n", "r": "\r"}.get(m.group(1), m.group(1)), text)


def _values(rest, predicate):
    """Every literal a predicate carries in a statement, as [(text, language)], wherever the
    predicate occurs in it."""
    out = []
    for found in re.finditer(r"(?<![\w:])" + re.escape(predicate) + r"\s+((?:" + LITERAL + r"\s*,?\s*)+)", rest):
        out += [(_unescape(text), lang or DEFAULT_LANGUAGE) for text, lang in re.findall(LITERAL, found.group(1))]
    return out


def _text(values):
    """Texts as the vocabulary writes them: one string in English, a map when there are others."""
    texts = {lang: text for text, lang in values}
    if not texts:
        return None
    return texts[DEFAULT_LANGUAGE] if list(texts) == [DEFAULT_LANGUAGE] else texts


def _annotations(rest, name, definitions=True):
    """label, alt_labels, definition, scope_note, example as the statement carries them. A label
    that only reads the name ("part of" for part_of) is the export's default, not a written one."""
    from .vocabulary import name_as_words
    spec = {}
    for key, predicate in (("definition", "skos:definition"), ("label", "skos:prefLabel"),
                           ("scope_note", "skos:scopeNote"), ("example", "skos:example")):
        if key == "definition" and not definitions:
            continue
        value = _text(_values(rest, predicate)) if key != "definition" else \
            _text(_values(rest, "skos:definition") or _values(rest, "rdfs:comment"))
        if value and not (key == "label" and value == name_as_words(name)):
            spec[key] = value
    alternatives = {}
    for text, lang in _values(rest, "skos:altLabel"):
        alternatives.setdefault(lang, []).append(text)
    if alternatives:
        spec["alt_labels"] = alternatives[DEFAULT_LANGUAGE] if list(alternatives) == [DEFAULT_LANGUAGE] else alternatives
    return spec


def _relation(name, domain, rng, inverse, rest):
    """A relation in the vocabulary's form; an absent range or inverse is left out."""
    spec = {"domain": domain}
    if rng:
        spec["range"] = rng
    if inverse:
        spec["inverse"] = inverse
    parent = re.search(r"rdfs:subPropertyOf\s+[\w-]+:([\w-]+)", rest)
    if parent:
        spec["subproperty_of"] = parent.group(1)
    spec.update(_annotations(rest, name))
    spec.setdefault("definition", "")
    return spec


def _attribute(attributes, name, holders, spec, rest):
    """Declare attribute `name` on each class that holds it. With several holders the export
    writes one definition per class, `Class: meaning`."""
    notes = _annotations(rest, name, definitions=False)
    comments = _values(rest, "skos:definition") or _values(rest, "rdfs:comment")
    scheme = IN_SCHEME.search(rest)
    for kind in holders:
        if len(holders) == 1:
            texts = comments
        else:
            texts = [(text[len(kind) + 2:], lang) for text, lang in comments if text.startswith(kind + ": ")]
        definition = _text(texts) or ""
        enum = ENUM_COMMENT.match(definition) if isinstance(definition, str) else None
        of = SCHEME_COMMENT.match(definition) if isinstance(definition, str) else None
        if isinstance(definition, dict):                     # several languages: the suffix is on each
            stripped = {lang: (SCHEME_COMMENT.match(d) or ENUM_COMMENT.match(d) or re.match(r"^(.*)$", d)).group(1) for lang, d in definition.items()}
            of = next((SCHEME_COMMENT.match(d) for d in definition.values() if SCHEME_COMMENT.match(d)), None)
            enum = next((ENUM_COMMENT.match(d) for d in definition.values() if ENUM_COMMENT.match(d)), None)
            definition = stripped
        declared = {"type": "scheme:" + of.group(2) if of else "scheme:" + scheme.group(1) if scheme else "enum:" + enum.group(2) if enum else spec,
                    "definition": (of.group(1) if of else enum.group(1) if enum else definition) if isinstance(definition, str) else definition}
        declared.update(notes)
        attributes.setdefault(kind, {})[name] = declared


def parse_turtle(text):
    classes, properties, notes = {}, {}, []
    attributes, inverse_labels, schemes = {}, {}, {}
    body = text.split(TEMPORAL_PREFIX)[0]        # the temporal block is shared, never imported
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    for statement in re.split(r"\s\.\s*\n", body):
        m = CLASS_STMT.match(statement)
        if m:
            classes[m.group(1)] = dict({"definition": ""}, **_annotations(m.group("rest"), m.group(1)))
            parents = re.findall(r"rdfs:subClassOf\s+[\w-]+:([\w-]+)", m.group("rest"))
            if parents:
                classes[m.group(1)]["subclass_of"] = parents
            continue
        m = SCHEME_STMT.match(statement)
        if m:
            schemes.setdefault(m.group(1), {"concepts": {}}).update(dict({"definition": ""}, **_annotations(m.group("rest"), m.group(1))))
            continue
        m = CONCEPT_STMT.match(statement)
        if m:
            concept = _annotations(m.group("rest"), m.group(2))
            broader = re.search(r"skos:broader\s+[\w-]+:[\w-]+\.([\w-]+)", m.group("rest"))
            if broader:
                concept["broader"] = broader.group(1)
            schemes.setdefault(m.group(1), {"definition": "", "concepts": {}})["concepts"][m.group(2)] = concept
            continue
        m = DATA_STMT.match(statement) or PROP_STMT.match(statement)
        if not m:
            continue
        rest = m.group("rest")
        domain = _target(rest, "rdfs:domain")
        inverse = INVERSE.search(rest)
        is_list = re.search(r"rdfs:range\s+rdf:List\b", rest) is not None
        is_concept = IN_SCHEME.search(rest) is not None or re.search(r"rdfs:range\s+skos:Concept\b", rest) is not None
        if "kind" in m.groupdict() or is_list or is_concept:      # an attribute: a datatype, a list, or a scheme's concepts
            if not domain:
                continue
            plain = re.search(r"rdfs:range\s+([\w-]+:[\w-]+)", rest)
            spec = XSD_TO_TYPE.get(plain.group(1) if plain else "xsd:string", "string")
            if m.groupdict().get("kind") == "rdf:Property" or re.search(r"rdfs:range\s+" + UNION, rest):
                spec = "string"
                notes.append("attribute %r is declared with different types on %s and the Turtle does not say "
                             "which is whose: read as string, declare the types again" % (m.group(1), domain))
            _attribute(attributes, m.group(1), domain.split("|"), spec, rest)
            continue
        if not domain and inverse:                  # a relation read from the other side: its label belongs to the relation
            inverse_labels[m.group(1)] = _text(_values(rest, "skos:prefLabel"))
            continue
        if not domain:
            notes.append("relation %r has no domain; skipped" % m.group(1))
            continue
        properties[m.group(1)] = _relation(m.group(1), domain, _target(rest, "rdfs:range"), inverse.group(1) if inverse else None, rest)
    from .vocabulary import name_as_words
    for relation, spec in properties.items():
        written = inverse_labels.get(spec.get("inverse"))
        if written and written != name_as_words(spec["inverse"]):
            spec["inverse_label"] = written
    if not classes and not properties:
        notes.append("no owl:Class or owl:ObjectProperty statements found; this reader handles the "
                     "one-statement-per-line Turtle OTO emits")
    if attributes:
        parse_turtle.attributes = attributes      # picked up by read()
    if schemes:
        parse_turtle.schemes = schemes
    return classes, properties, notes


def parse_csv(text):
    classes, properties, notes = {}, {}, []
    rows = list(csv.DictReader(text.splitlines()))
    if not rows or "kind" not in rows[0] or "name" not in rows[0]:
        return {}, {}, ["expected a header with at least: kind, name, description, domain, range, inverse"]
    for number, row in enumerate(rows, 2):
        kind = (row.get("kind") or "").strip().lower()
        name = (row.get("name") or "").strip()
        if not name:
            notes.append("row %d has no name; skipped" % number)
            continue
        if kind == "class":
            classes[name] = {"definition": (row.get("description") or "").strip()}
        elif kind in ("relation", "property"):
            domain, rng = (row.get("domain") or "").strip(), (row.get("range") or "").strip()
            if not domain:
                notes.append("row %d: relation %r has no domain; skipped" % (number, name))
                continue
            properties[name] = _relation(name, domain, rng, (row.get("inverse") or "").strip(), "")
            properties[name]["definition"] = (row.get("description") or "").strip()
        elif kind == "attribute":
            owner, spec = (row.get("domain") or "").strip(), (row.get("range") or "string").strip()
            if not owner:
                notes.append("row %d: attribute %r names no class in the domain column; skipped" % (number, name))
                continue
            parse_csv.attributes = getattr(parse_csv, "attributes", None) or {}
            parse_csv.attributes.setdefault(owner, {})[name] = {"type": spec, "definition": (row.get("description") or "").strip()}
        else:
            notes.append("row %d: kind %r is not class or relation; skipped" % (number, kind))
    return classes, properties, notes


def parse_json(text):
    payload = json.loads(text)
    classes = dict(payload.get("classes") or {})
    properties = dict(payload.get("properties") or {})
    notes = [] if (classes or properties) else ["no classes or properties in the file"]
    if payload.get("attributes"):
        parse_json.attributes = {k: dict(v) for k, v in payload["attributes"].items()}
    if payload.get("schemes"):
        parse_json.schemes = dict(payload["schemes"])
    return classes, properties, notes


READERS = {".ttl": parse_turtle, ".csv": parse_csv, ".json": parse_json}


def read(path):
    """(classes, properties, notes) from a file, by extension. `read.attributes`, `read.schemes`,
    `read.namespaces` and `read.rationale` hold what else the file carried."""
    from . import rdf_import
    ext = os.path.splitext(path)[1].lower()
    read.attributes, read.schemes, read.namespaces, read.rationale = {}, {}, None, None
    if ext in rdf_import.FORMATS and rdf_import.available():
        result = rdf_import.read(path)
        read.attributes, read.schemes = rdf_import.read.attributes, rdf_import.read.schemes
        read.namespaces, read.rationale = rdf_import.read.namespaces, rdf_import.read.rationale
        return result
    if ext in rdf_import.FORMATS and ext != ".ttl":
        raise ValueError("%s: reading %s needs rdflib: pip install \"oto-kg[rdf]\"" % (path, ext))
    if ext not in READERS:
        raise ValueError("%s: unsupported vocabulary file. Use %s, or read it and write "
                         "ontology.config.json directly." % (path, ", ".join(sorted(READERS))))
    reader = READERS[ext]
    reader.attributes, reader.schemes = {}, {}
    with open(path, encoding="utf-8") as f:
        result = reader(f.read())
    read.attributes = getattr(reader, "attributes", {}) or {}
    read.schemes = getattr(reader, "schemes", {}) or {}
    return result


def check(classes, properties, attributes=None, schemes=None):
    """What is wrong with a vocabulary before it is written."""
    from .vocabulary import declaration_problems, shape_problems

    problems = shape_problems({"classes": classes, "properties": properties})
    if problems:
        return problems
    problems = declaration_problems(classes, attributes or {}, schemes or {})
    if not classes:
        problems.append("no classes")
    for kind, spec in classes.items():
        if not (spec.get("definition") or "").strip():
            problems.append("class %r has no definition" % kind)
    for relation, spec in properties.items():
        for position in ("domain", "range"):
            for kind in [x.strip() for x in (spec.get(position) or "").split("|") if x.strip()]:
                if kind not in classes:
                    problems.append("relation %r names undeclared class %r" % (relation, kind))
        if not (spec.get("definition") or "").strip():
            problems.append("relation %r has no definition" % relation)
    return problems


def apply(project, classes, properties, rationale=None, replace=False, attributes=None, namespaces=None, schemes=None):
    """Write the vocabulary into the project. Refuses to overwrite a declared one unless `replace`.

    Keeps the project's name, version and temporal vocabulary. Merges a rationale in without
    overwriting entries a person has already written. `namespaces` says which ontology each term
    came from (model/namespaces.py); a vocabulary read from a file has none, and its terms become
    the project's own.
    """
    from . import rationale as _rationale

    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    if (config.get("classes") or config.get("properties")) and not replace:
        raise ValueError("ontology.config.json already declares %d class(es) and %d relation(s). Pass "
                         "--replace to overwrite them, or edit the file."
                         % (len(config.get("classes") or {}), len(config.get("properties") or {})))
    config["classes"] = dict(classes)
    config["properties"] = dict(properties)
    if attributes:
        config["attributes"] = {k: dict(d) for k, d in attributes.items()}
    elif replace:
        config.pop("attributes", None)
    if schemes:
        config["schemes"] = schemes
    elif replace:
        config.pop("schemes", None)
    if namespaces:
        config["namespaces"] = namespaces
    elif replace:
        config.pop("namespaces", None)
    config.setdefault("ontology_version", 1)
    config.setdefault("strict_domains", False)
    with open(project.ontology_config_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if rationale:
        record = _rationale.load(project)
        for section in ("classes", "properties"):
            record.setdefault(section, {})
            for key, entry in (rationale.get(section) or {}).items():
                record[section].setdefault(key, dict(entry))
        _rationale.save(project, record)
    return project.ontology_config_path
