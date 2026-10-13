# Changelog

What each engine release changed for the people who write ontologies, run projects, or read the
exports. Ontologies and packs carry their own `release` and changelog in their manifests; this
file is the engine's.

## 0.11.13 — 2026-10-13

**The concierge knows the project's packs.** `oto status` gains a `packs` section: each plugin the
project uses (its `.claude/settings.json`, else the OTO plugins installed for it), with its version,
its skills and its views; a declared plugin not installed here says so, with its install line.
`oto status --json` gives each skill's command (`/<pack>:<skill>`) and what it does. The concierge
quotes the section when it orients and routes to a pack's skill first when the need is what the
pack does (model a part with DDD, design a pipeline, define a report); until now its hand-off table
knew only OTO's own skills.

## 0.11.12 — 2026-10-13

**A project declares the plugins it uses.** `oto init` from installed packs writes the project's
`.claude/settings.json` as Claude Code's project scope does (`enabledPlugins`,
`extraKnownMarketplaces`): the `--pack`, the pack of every ontology the project composes, named or
extended (the `ddd` pack for its skills although `ddd` ships with the engine; `report` under
`product-report`), and the engine plugin. Whoever opens the project is offered the same plugins, and
the lock records exactly those. `oto lock --use <name@marketplace>,...` declares a tool no ontology
brings, such as `pdf-to-template`. Other settings in the file are kept.

## 0.11.11 — 2026-10-13

**A project records the tools it is built with.** `oto.lock.json`, written by `oto init` and
`oto lock`, holds the engine's version (and commit when it runs from a checkout), each Claude Code
plugin the project uses with its marketplace, version and commit, each marketplace with its commit,
and the ontology record. The plugins are those the project's `.claude/settings.json` enables, else
the OTO plugins installed for it. `oto lock --check` and a new `tools` line in `oto status` say how a
machine differs; `oto lock --script` prints the script that rebuilds the tools on a fresh machine or
in a container: marketplaces cloned at their commits (Claude Code pins a branch or a tag, not a
commit), plugins installed from them, the engine from its commit or tag, named in `OTO_SOURCE`.
Every version that reaches main is now tagged `v<version>` (a workflow), so the engine of a lock can
be pinned. Auditable, repeatable, shareable: a project says what built it.

## 0.11.10 — 2026-10-13

**A pack can take the place of a plugin.** `oto pack publish` of a pack named like a plugin the
registry lists from its own repository (`oto registry plugin`; a studio that became a pack) replaces
that entry, so the marketplace lists one plugin under the name, and continues its version line: the
studio plugin at 2.0.0 becomes the pack at release 3, 3.0.0. Claude Code caches a plugin by version,
so a pack published at a version the old plugin once had would be served from the stale cached copy.
The publish says what it replaced. `data` is a known domain (a data pipeline's packs).

## 0.11.9 — 2026-10-13

**The shipped `product` ontology names no client.** Its release 1 changelog entry named the project
it was exported from; it now says it came from a client project. Nothing else changes: same release,
same vocabulary. Packs that embed `product` pick it up on `oto pack refresh`.

## 0.11.8 — 2026-10-13

**An installed pack's ontologies resolve by name.** `oto init --ontology <name>` (alone, merged, or
beside `--pack`) finds an ontology embedded in an installed pack: one under `~/.oto/packs`
(`OTO_PACKS`), or a pack Claude Code installed as a plugin, read from its list of installed plugins
(`CLAUDE_CONFIG_DIR`, default `~/.claude`). A machine that installed the `product-report`, `ddd` and
`flow` packs from a marketplace could not name them (`unknown ontology 'product-report'`): only
`~/.oto/ontologies` and the shipped set were searched. Packs come last, after yours and the shipped
ones, so a pack's copy of a base it extends never shadows them; when two packs carry the same
ontology, the higher release wins. An ontology found in a pack composes with the bases that pack
carries, the copies it was checked with, as `--pack` composes. The project records the pack and the
origin the pack recorded on embedding; `oto ontology list` marks these `(in a pack)`.

## 0.11.7 — 2026-10-13

**A rule can say what is absent, with conditions.** `{"not": [patterns]}` in a policy rule or a
question keeps a binding only when the patterns match nothing from it, so the absent node may carry
conditions and reach variables bound outside it: "a step that builds a silver entity and comes after
no gate-1 step". `not_edge` could only say there was no edge at all. The `not_in` operator is the
complement of `in` (an absent value is not outside the list, as SPARQL's `NOT IN`). Both render to
SPARQL (`FILTER NOT EXISTS`, `NOT IN`) and answer the same there; a derivation stays positive. Needed
by the medallion flow validations, which are rules over a declared flow.

## 0.11.6 — 2026-10-12

**A view can carry what a pattern adds.** `{"$optional": expr}` in the projection language marks a
part that may name classes and relations the vocabulary lacks. It is evaluated as is, so in a
project without them it is empty (a collection over a class the graph does not hold already is),
and validation (`oto pack check`, a template's self-check, serving) does not require what only an
optional part names; a class named outside one is still checked. A studio's site can show the DDD
pages of a product that adds `ddd`, or later a pipeline's layers, without its pack embedding them.

## 0.11.5 — 2026-10-12

**A pack and the ontologies a product adds.** `oto init --pack <pack> --ontology <name>,...`
merges the named ontologies with the pack's, as `--ontology a,b` merges, and installs the pack's
views. It was refused ("pass --ontology or --pack, not both"), so a pack could not be the core a
product extends: a studio pack embeds what every product shares, and each product adds its type
(`product-report`) and the flow. `merge` finds a name in the pack's embedded copy first, as
`composed` does; the project records the merge, with the pack on its first part and beside the
record, so `oto status` still says which pack it came from. The generated `start` skill mentions
the option. A pack's manifest may carry a `title`: a pack broader than its ontology (a studio over
`ddd`) is then shown under its own name, not the ontology's.

## 0.11.4 — 2026-10-12

**Skills that sound alike say which is which.** Descriptions only, no behaviour: `start` and
`build-knowledge-base` both answered "build me a knowledge base"; `start` is for choosing the way
in, `build-knowledge-base` for documents already in hand. `spec` writes a spec, an ADR or a brief
*from* the graph, and names capture-form and a studio's prd-build and architecture-build for
capturing one *into* it. `query-knowledge` lets a pack's own question skill (the report pack's
ask-reports) answer its domain first.

## 0.11.3 — 2026-10-12

**A pack's `start` hands over to the pack's own skills.** The generated starter skill told every
pack to run ontology-interview and hand over to build-knowledge-base and query-knowledge, so a pack
that ships `new-report` or `implement-step` sent people away from them. When a pack ships skills
beside `start`, step 2 now names each one (`<pack>:<skill>`, with the first clause of its
description) and step 3 lists the engine's skills for what they do not cover, capture-form among
them. A pack with no skills of its own is generated as before. `packs.frontmatter` reads a
SKILL.md's frontmatter for both the generator and the registry site. Takes effect when a pack is
regenerated: `oto pack refresh` or `oto pack publish`.

## 0.11.2 — 2026-10-12

**The capture form has one playbook.** The skill **capture-form** fills a project's
`capture.json` with a person: the questions group by group, the items drafted and confirmed,
every confirmed group through `oto curate start`, `propose`, `add`, `check` and `apply`. A pack's
or a studio's interview runs it and adds only what its domain needs; the studio's `capture` and
the report pack's `new-report` no longer carry their own copy. The loop now starts a candidate
first: both copies went straight to `oto curate add`, which refuses without one.

## 0.11.1 — 2026-10-09

**Plugins in their own repositories, in the marketplace.** A plugin that depends on `oto` (a
studio, a tool) resolves that dependency inside its own marketplace, so it must be listed beside
the engine: `oto registry plugin <name> --to <registry> --repo owner/name [--plugin-ref, --path,
--version, --description, --category]` lists it in the registry's index and marketplace
(`--remove` delists); named `oto`, it says where the engine comes from, a branch under test
included. **A checkout as the engine**: the plugin's MCP server and session hook run
`OTO_SOURCE` when it is set, the published engine otherwise.

## 0.11.0 — 2026-10-07

**The portfolio and the work** (stage 5, B6; decided and confirmed with Chiheb Dkhil). `portfolio`
@1 is the base of the chain: Product (its stage, domain, value stream, and where its knowledge
lives), Role, Team, Objective and Capability are declared once; `product` @9 sits on it,
`software-architecture` @10 on that, `ddd` unchanged. The executive's questions PF1–PF10: what we
build, what we pursue, what depends on what, which capability has no product, what has no owner,
where a product's store and packs are. `work` @1 on `software-architecture`: work items and
milestones that deliver requirements, features and components, assigned, scheduled, blocked; the
delivery lead's questions WK1–WK10, among them *which requirements slip if this component is
late*, and a derived `blocked` state.

**A row that says nothing is no answer.** A question's row whose selected values are all absent
is dropped, as SPARQL drops it; a question that selects only absent attributes is unanswered.

**Patterns are `sh:pattern`.** An attribute's `pattern` matches anywhere in the value; anchor it
for the whole. The importer reads SHACL decimals as numbers.

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
