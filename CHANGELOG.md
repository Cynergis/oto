# Changelog

What each engine release changed for the people who write ontologies, run projects, or read the
exports. Ontologies and packs carry their own `release` and changelog in their manifests; this
file is the engine's.

## 0.7.0 — 2026-10-06

The semantic layer. OTO is still before its first announced release, so nothing here keeps an
older form alive: an ontology or pack written for 0.6 is rewritten, or it is not usable.

**Vocabulary form.** Every declaration is an object. A class is `{definition, label, alt_labels,
scope_note, example, subclass_of}`; a relation is `{domain, range, inverse, definition, label,
inverse_label, ..., subproperty_of}`; an attribute or temporal term is `{type, definition, ...}`.
The list and string forms are gone. `tools/convert_ontology.py` rewrites an old directory in
place and keeps the previous files beside it.

**Namespaces.** Each ontology declares `namespace` in its manifest (`https://cynergis.ai/ont/<name>#`
for the shipped ones); it is required. Terms an ontology inherits through `extends` keep the IRI
of the ontology that declared them; a project's own terms live under `<project namespace>ont/`,
its instances under `<project namespace>id/`. The `namespaces` section of a vocabulary records
what is claimed, inherited and renamed.

**RDF export is correct.** `rdf:type` instead of a custom predicate, per-ontology term IRIs,
`owl:unionOf` for union domains and ranges, typed literals, RDF collections for lists, `rdf:JSON`
for structured values, temporal terms as `owl:AnnotationProperty`, and `graph.ttl` beside
`graph.json` on every build. The Turtle and JSON-LD of an ontology carry `rdfs:label`,
`skos:prefLabel`, `skos:altLabel`, `skos:definition`, `rdfs:comment`, `skos:scopeNote`,
`skos:example`, `rdfs:subClassOf`, `rdfs:subPropertyOf` and inverse declarations.

**Labels and languages.** A term is read by its name unless a label is written; `languages`
declares what a vocabulary speaks and English is the default. Stores hold a `terms` table and an
`aliases` table with kind and language (SQLite schema 5; Neo4j `Term` nodes); cards, the explorer
and `kg_entity` show labels; `kg_define` and `oto query define` answer what a term means.

**Reasoning kept.** Rationale travels with the lock and the export as `meta:` annotations
(`https://cynergis.ai/ont/meta#`); a change of superclass or of a concept's place is a breaking
change the lock reports, and RECONFIRM asks a person again.

**Hierarchy.** `subclass_of` and `subproperty_of` are closed over by the vocabulary; stores,
rules (`covers`), action readiness, conformance and inherited attributes honour them, so a query
for a class answers with its subclasses.

**Concept schemes.** `schemes` declares controlled values as SKOS concepts with label, definition
and `broader`; an attribute typed `scheme:<name>` takes one of them, and the auto-claims ontology
uses them for claim and task states. `enum:` remains for a flat list.

**Import.** `oto ontology import` reads Turtle, RDF/XML, JSON-LD and N-Triples through rdflib
(the `rdf` extra), including unions, parents, inverse-only properties, list attributes and
concept-valued attributes; the report ontology is the acceptance fixture. Without rdflib, a
Turtle written by OTO still reads.

**Shipped ontologies and packs** are rewritten in this form and released again; the registry was
recreated from them.

**Skills.** `build-knowledge-base` ships the two references it pointed at: `draft-proposal.md`,
the rules a drafting subagent keeps, and `pipeline-run.md`, the unattended rules of the author
workflow.

## 0.6.1 — 2026-09-27

First published tree: the engine, its skills, its ontologies and its documentation.
