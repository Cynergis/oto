# Changelog

What each engine release changed for the people who write ontologies, run projects, or read the
exports. Ontologies and packs carry their own `release` and changelog in their manifests; this
file is the engine's.

## 0.8.2 — 2026-10-07

**The capture schema and proposals from a capture** (stage 2 of the programme). `oto ontology
capture` renders `capture.json` from a pack or a project: the questions by asker with their gates,
the classes with their fields, links and what they require, every field and link carrying `x-term`;
the build writes it beside `questions.yaml`. `oto curate propose --from <capture>` checks what a
tool captured against the schema and writes a proposal cited to the document, for the gates.

**Also.** `oto ontology import --from` carries the ontology's rules and questions; a forced export
is the next release of an ontology that exists; `oto-core` @5's sample carries its date as `as_of`.

## 0.8.1 — 2026-10-06

**The start skill** (`/oto:start`): a new project from whatever the person has (a specification,
a folder of documents, a domain expert, an ontology or pack that is close), to the first
confirmed questions and a hand-off to the interview. Found by starting the report ontology
from scratch: the path from a specification existed inside the interview skill and nobody
looking for it could find it. The concierge, `oto status` and the README point at it.


What porting the report ontology (github.com/Cynergis/report-ontology, `oto/report`) as an OTO
unit needed of the pattern language, so its 21 SPARQL questions could be written once in the
form the engine runs:

- `optional`: a list of patterns that extend a binding when they match and leave their variables
  unbound when they do not (a left join), in questions and policies; rendered as `OPTIONAL { }`,
  with the filters and the selection's reads of its variables placed inside the block.
- `{"exists": false}` on an attribute, and a `where` value that refers to a bound variable:
  `"$REPORT"` is its id, `"$FIELD.fieldId"` one of its attributes, `"fields.$FIELD.fieldId."`
  splices it into text; rendered as the bound variable, a triple, or `CONCAT`.
- `gaps` as a list of `{when, say}`: every cause that holds is reported.
- A declared attribute named like a node's own field (`label`) is the term even when a node
  carries no value for it: the engine no longer answers the node's label for a missing
  `rpt:label`, which the SPARQL rendering had exposed.



Questions that run, and shapes that gate. An ontology without competency questions, or whose
sample cannot answer them, is not usable from this release on; the shipped ontologies and the
registry packs are republished with theirs.

**Competency questions.** `questions.json` beside the vocabulary (`reason/questions.py`): each
question with who asks it, why, an `ask` in the pattern language of the rules (`when` + `select`,
`$NAME` parameters), a `gate` (`non_empty`, `empty`, `any`) and a `gaps` pattern that says why an
answer is empty. They ride in the store (SQLite schema 6, Neo4j `Question` nodes): `kg_questions`
surveys every question over the live graph, `kg_ask` runs one with its parameters bound (ids,
labels or aliases), `oto query questions` / `oto query ask` and `/api/questions` / `/api/ask` are
the other faces. Questions are carried by the ontology unit (`carries`), merged by id through
`extends`, installed by `oto init`, exported with `validated_by` blanked, locked, and diffed
(a changed `ask`, `params` or `gate` is breaking; added is additive; reworded is cosmetic).

**The contract.** Every class, relation and attribute must be cited by a question that runs, and
an ontology's sample must answer every question it must: the self-check refuses otherwise, `oto
ontology check` prints the terms no question cites and the questions the live graph cannot
answer (`--strict` fails), and `oto ontology accept` refuses an uncovered vocabulary.

**Shapes.** A relation's `min` and `max`, an attribute's `required`, a class's `requires`
(`reason/shapes.py`), evaluated over current facts with the hierarchy honoured; a policy rule may
say which question it protects (`answers`). `oto curate check` blocks a candidate that breaks a
shape or leaves a required question unanswered; `oto ontology check` prints the declared shapes
and the live graph's violations; the self-check holds the sample to them. Tightening is breaking
in the lock, loosening additive.

**Rendered for everyone else.** The ontology Turtle carries the shapes as SHACL (`sh:NodeShape`,
`sh:property` with counts; each policy rule as a `sh:SPARQLConstraint`), and `oto ontology import`
reads the property shapes back. `questions.yaml` holds every question rendered as SPARQL over
`graph.ttl` (`compile/sparql.py`); `ontology.md` lists the shapes and the questions. Tests with
rdflib and pyshacl (dev extras) require the SPARQL to return the engine's rows and the SHACL to
find the engine's violations.

**Also.** A declared attribute named like a node's own field (`status`) now wins in rules and
questions when the node carries it; the invented sample of an export exercises every pair of
domain and range, respects `max`, and gives twins their attributes; the skills (ontology-interview
Phase 4d, build-knowledge-base, curate, query-knowledge) know the questions and the gate.

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
