# Changelog

What each engine release changed for the people who write ontologies, run projects, or read the
exports. Ontologies and packs carry their own `release` and changelog in their manifests; this
file is the engine's.

## 0.10.0 — 2026-10-07

**Value constraints** (stage 5, A4). An attribute may declare `pattern`, `min_value`, `max_value`
(a number, or an ISO date for a date) and `min_length`; the engine holds every value to them
(`oto curate check`, `oto ontology check`, the self-check on a sample), the Turtle carries them as
`sh:pattern`, `sh:minInclusive`, `sh:maxInclusive`, `sh:minLength`, the importer reads them back,
and pyshacl agrees with the engine. The report shapes the port could not hold can be held now.

**Product types** (A7). An ontology's manifest may declare `product_type` (`product-report`
declares `report`); the pack and the registry index carry it; `oto ontology list --product-types`
and `oto registry list --product-types` list the kinds of product a studio can start, so its first
question is read from the marketplace.

**The survey is cached** (A6): `kg_questions` runs every question once per loaded build.

## 0.9.3 — 2026-10-07

**A relation may be `derived`.** The rules state it and nobody captures it: the capture schema
leaves it out, so a tool never asks a person for what the engine concludes (the flow's
`dependsOn`, `requiresTest`). The capture schema also lists the pack's briefs. The self-check
asks an ontology's questions of its sample as a build would, with what the rules derive.

## 0.9.2 — 2026-10-07

**Briefs** (stage 3, A3). `briefs.json` beside the questions: a task type with its parameters,
the questions it requires and the ones it may also read. `oto query brief <task> NAME=<entity>`
and `kg_brief` are READY with every required question's facts or BLOCKED by name with the gaps;
without the parameters, the table for every candidate. Briefs compose by task, ride in the store
beside the questions, and are carried by an ontology (`carries`: `briefs`). Built for the port
of the flow ontology (report-ontology `oto/flow`), whose five task types give `kgctl brief`'s
verdicts for every step.

**The `no_gaps` gate.** A question whose answer may be empty but whose gaps always run; the
original's `gaps_only`. `may_continue` in the capture schema treats it as required.

## 0.9.1 — 2026-10-07

**A product starts from what its people say.** `oto init --empty` installs the vocabulary and
leaves the graph empty (no sample, no lexicon seed): the studio's Atlas starts every product this
way, so the pack's example never answers a question about the person's product. An empty graph
builds, and `oto query questions` says what is open. Found by scene 4 of the studio: the fund
report product's design was being checked against a payments platform.

**A question reports; a policy refuses.** `oto curate check` lists a required question the
candidate leaves unanswered under gaps, not blocking: facts arrive section by section, and the
question answered later must not refuse the fact that arrives first. A malformed capture item
(`fields` not an object) is refused by name.

## 0.9.0 — 2026-10-07

**The design level** (stage 3 of the programme, B4). Three shipped ontologies now form one chain:
`product` @8 ships with the engine (it was a user pack); `software-architecture` @9 sits on it,
dropping its own Requirement, Risk, Document and DecisionRecord for the product's and widening
`part_of`, `owned_by`, `about`, `threatens`, `mitigated_by` and `documented_in` to the estate
(`supports` is `enables`; SA17 asks which requirements nothing satisfies yet); `ddd` @1,
generalised out of `ddd-kyc`, sits on `software-architecture`: subdomains, bounded contexts and
their map, use cases, events, commands, reactions, read models, external systems, aggregates,
entities, value objects, business rules, domain services, with `deployed_as` from a context to a
component and `satisfies` from a use case to a requirement. The event-storming policy is
`Reaction`, because the product's `Policy` is a rule from outside. Decided with Chiheb Dkhil.

**A merge widens.** Two packs that widen the same relation of a shared base (`product-report` and
`ddd` both widen `part_of`) merge to the union of both signatures, as composition widens, and the
clash is reported; before, the first declaration won and the second pack's facts were refused.

**An export ships the graph.** `oto ontology export` and `publish` take the project's graph as the
sample (privacy-scanned, `--from-graph N` to cap it); `--invented` gives the synthetic one, which
answers the questions but respects no policy. A project started from a pack therefore exports
the pack's sample it still holds.

**Also.** A shipped ontology may carry a confirmation that names the person and the day; the
product's `risk-reaches-product` is typed to the feature and the product, so the estate's
`risk-reaches-system` derives its own hop; the `product` domain is known to the engine.

## 0.8.3 — 2026-10-07

**A capture names its scope.** A document's ids (`FR1`, `P1`) are unique in the document, not in
the graph: a capture may say which product it is about (`"scope": "fund-report"`) and its nodes
are `requirement.fund-report.fr1`, so two products' `FR1` stay apart. Found by the studio's scene
tests, whose fixture collided with the `product` pack's own sample.

**A project composed of several packs keeps their samples.** `oto init --ontology a,b` merges
the parts' samples by node id instead of inventing a synthetic one, and an ontology's self-check
runs its blocking policies on its sample: a pack whose sample breaks its own policy is refused.

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
