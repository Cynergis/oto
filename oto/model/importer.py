# -*- coding: utf-8 -*-
"""Bring a vocabulary in from outside: an ontology, a file OTO emitted, or a plain list.

A team that already owns a vocabulary should not retype it, and an agent that translates it by
hand should not be the only check on the translation. So the formats OTO can verify are read here,
and everything else stays a reading job for a person or an agent, whose result still lands in the
same config and passes the same gates.

Sources:

    --ontology a[,b]     shipped or exported ontologies, merged if more than one
    file.ttl             the Turtle OTO itself emits (owl:Class / owl:ObjectProperty, one statement
                         per line), so a vocabulary round-trips between projects
    file.csv             one row per term: kind, name, description, domain, range, inverse
                         (kind `attribute`: domain is the class, range is the type)
    file.json            the shape of ontology.config.json: {"classes": {...}, "properties": {...}}

Nothing here writes a rationale. An imported class has no recorded reason yet, and inventing one
would be worse than none. `oto ontology rationale` reports the gap; the interview fills it.
"""
import csv
import json
import os
import re

CLASS_STMT = re.compile(r"^\s*\w+:(\w+)\s+a\s+owl:Class\b(?P<rest>.*)$", re.S)
DATA_STMT = re.compile(r"^\s*\w+:(\w+)\s+a\s+owl:DatatypeProperty\b(?P<rest>.*)$", re.S)
XSD_TO_TYPE = {"xsd:string": "string", "xsd:decimal": "number", "xsd:double": "number", "xsd:float": "number",
               "xsd:integer": "integer", "xsd:int": "integer", "xsd:boolean": "boolean", "xsd:date": "date",
               "rdf:List": "list"}
ENUM_COMMENT = re.compile(r"^(.*?)\s*\(one of: ([^)]*)\)\s*$")
PROP_STMT = re.compile(r"^\s*\w+:(\w+)\s+a\s+owl:ObjectProperty\b(?P<rest>.*)$", re.S)
COMMENT = re.compile(r'rdfs:comment\s+"((?:[^"\\]|\\.)*)"')
DOMAIN = re.compile(r"rdfs:domain\s+([^;.]+?)\s*(?:;|$)")
RANGE = re.compile(r"rdfs:range\s+([^;.]+?)\s*(?:;|$)")
INVERSE = re.compile(r"owl:inverseOf\s+\w+:(\w+)")
TEMPORAL_PREFIX = "# --- temporal"


def _names(spec):
    """`acme:Policy, acme:Party` -> `Policy|Party`."""
    return "|".join(x.strip().split(":")[-1] for x in spec.split(",") if x.strip())


def parse_turtle(text):
    classes, properties, notes = {}, {}, []
    attributes = {}
    body = text.split(TEMPORAL_PREFIX)[0]        # the temporal block is shared, never imported
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    for statement in re.split(r"\s\.\s*\n", body):
        m = CLASS_STMT.match(statement)
        if m:
            comment = COMMENT.search(m.group("rest"))
            classes[m.group(1)] = (comment.group(1) if comment else "").replace('\\"', '"')
            continue
        m = DATA_STMT.match(statement)
        if m:
            rest = m.group("rest")
            domain, rng, comment = DOMAIN.search(rest), RANGE.search(rest), COMMENT.search(rest)
            if not domain:
                continue
            kind = _names(domain.group(1))
            spec = XSD_TO_TYPE.get((rng.group(1).strip() if rng else "xsd:string"), "string")
            desc = (comment.group(1) if comment else "").replace('\\"', '"')
            enum = ENUM_COMMENT.match(desc)
            if enum:
                desc, spec = enum.group(1), "enum:" + enum.group(2)
            attributes.setdefault(kind, {})[m.group(1)] = [spec, desc]
            continue
        m = PROP_STMT.match(statement)
        if m:
            rest = m.group("rest")
            domain, rng, comment, inverse = DOMAIN.search(rest), RANGE.search(rest), COMMENT.search(rest), INVERSE.search(rest)
            if not domain:
                notes.append("relation %r has no domain; skipped" % m.group(1))
                continue
            properties[m.group(1)] = [_names(domain.group(1)), _names(rng.group(1)) if rng else None,
                                      inverse.group(1) if inverse else None,
                                      (comment.group(1) if comment else "").replace('\\"', '"')]
    if not classes and not properties:
        notes.append("no owl:Class or owl:ObjectProperty statements found; this reader handles the "
                     "one-statement-per-line Turtle OTO emits")
    if attributes:
        parse_turtle.attributes = attributes      # picked up by read()
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
            classes[name] = (row.get("description") or "").strip()
        elif kind in ("relation", "property"):
            domain, rng = (row.get("domain") or "").strip(), (row.get("range") or "").strip()
            if not domain:
                notes.append("row %d: relation %r has no domain; skipped" % (number, name))
                continue
            properties[name] = [domain, rng or None, (row.get("inverse") or "").strip() or None,
                                (row.get("description") or "").strip()]
        elif kind == "attribute":
            owner, spec = (row.get("domain") or "").strip(), (row.get("range") or "string").strip()
            if not owner:
                notes.append("row %d: attribute %r names no class in the domain column; skipped" % (number, name))
                continue
            parse_csv.attributes = getattr(parse_csv, "attributes", None) or {}
            parse_csv.attributes.setdefault(owner, {})[name] = [spec, (row.get("description") or "").strip()]
        else:
            notes.append("row %d: kind %r is not class or relation; skipped" % (number, kind))
    return classes, properties, notes


def parse_json(text):
    payload = json.loads(text)
    classes = dict(payload.get("classes") or {})
    properties = {k: list(v) for k, v in (payload.get("properties") or {}).items()}
    notes = [] if (classes or properties) else ["no classes or properties in the file"]
    if payload.get("attributes"):
        parse_json.attributes = {k: dict(v) for k, v in payload["attributes"].items()}
    return classes, properties, notes


READERS = {".ttl": parse_turtle, ".csv": parse_csv, ".json": parse_json}


def read(path):
    """(classes, properties, notes) from a file, by extension. `read.attributes` holds any
    per-class attribute declarations the file carried."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError("%s: unsupported vocabulary file. Use %s, or read it and write "
                         "ontology.config.json directly." % (path, ", ".join(sorted(READERS))))
    reader = READERS[ext]
    reader.attributes = {}
    with open(path, encoding="utf-8") as f:
        result = reader(f.read())
    read.attributes = getattr(reader, "attributes", {}) or {}
    return result


def check(classes, properties, attributes=None):
    """What is wrong with a vocabulary before it is written."""
    from .vocabulary import declaration_problems

    problems = declaration_problems(classes, attributes or {})
    if not classes:
        problems.append("no classes")
    for kind, description in classes.items():
        if not (description or "").strip():
            problems.append("class %r has no description" % kind)
    for relation, spec in properties.items():
        if len(spec) < 4:
            problems.append("relation %r is not [domain, range, inverse, description]" % relation)
            continue
        for position in (0, 1):
            for kind in [x.strip() for x in (spec[position] or "").split("|") if x.strip()]:
                if kind not in classes:
                    problems.append("relation %r names undeclared class %r" % (relation, kind))
        if not (spec[3] or "").strip():
            problems.append("relation %r has no description" % relation)
    return problems


def apply(project, classes, properties, rationale=None, replace=False, attributes=None):
    """Write the vocabulary into the project. Refuses to overwrite a declared one unless `replace`.

    Keeps the project's name, version and temporal vocabulary. Merges a rationale in without
    overwriting entries a person has already written.
    """
    from . import rationale as _rationale

    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    if (config.get("classes") or config.get("properties")) and not replace:
        raise ValueError("ontology.config.json already declares %d class(es) and %d relation(s). Pass "
                         "--replace to overwrite them, or edit the file."
                         % (len(config.get("classes") or {}), len(config.get("properties") or {})))
    config["classes"] = dict(classes)
    config["properties"] = {k: list(v) for k, v in properties.items()}
    if attributes:
        config["attributes"] = {k: {a: list(v) for a, v in d.items()} for k, d in attributes.items()}
    elif replace:
        config.pop("attributes", None)
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
