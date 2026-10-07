# How OTO is put together

Read this once, top to bottom, and the repository should be navigable without a guide. The package
is laid out in the order a project moves through it, and so is this page.

## One sentence

An OTO **project** is a directory of data. The **engine** is this package, installed once. The engine
turns the project's declared vocabulary and curated graph into a queryable store, refuses to build
anything that contradicts the vocabulary, and serves the store to an agent with a date and a
citation on every fact.

## The lifecycle, and the code behind each step

```
  oto init ──► oto ingest ──► (declare, author) ──► oto build ──► oto query / oto serve
  scaffold      intake/        model/  curate/        validate/     serve/
                                                      compile/
                                                      targets/
                                                      builder.py
                     ▲                                                     │
                     └────── oto feedback ◄──── oto bench ◄────────────────┘
                             bench/feedback.py  bench/
```

| Step | Command | Code | What it does |
|---|---|---|---|
| Create | `oto init`, `oto ontology`, `oto ontology export` | [scaffold.py](../oto/scaffold.py), [model/ontologies.py](../oto/model/ontologies.py) | Writes the identity config, a vocabulary, an empty or sample graph, and the directory tree. Nothing else is copied: the engine stays installed. `export` turns a project's accepted vocabulary into an ontology for the next project. |
| Ingest | `oto ingest`, `oto ingest complete`, `oto figures`, `oto survey` | [intake/](../oto/intake/) | A run claims the inbox into `processing/`, and each file becomes one `Document` of typed blocks through a registered extractor, is rendered to Markdown, given figure descriptions, scanned for personal data, and only then written to the corpus. Failures go to `errors/<run>/` with the reason beside them. `complete` moves a run's files to `archive/` once the graph holds their facts. `survey` maps the corpus, and `survey --doc` briefs one document for whoever drafts its proposal: its terms, and which already resolve to entities. |
| Declare | `oto ontology`, `oto ontology import`, `oto ontology` | [model/](../oto/model/) | The vocabulary lives in `ontology.config.json`. It arrives from an ontology (a versioned, composable unit: see Ontologies below) or several merged, from a file (any OWL, RDFS or SKOS ontology in any RDF syntax through the `rdf` extra, [model/rdf_import.py](../oto/model/rdf_import.py): every class, relation, attribute, union, parent, scheme, label, definition and recorded reason, each term keeping its IRI, and what cannot be held reported; without the extra the Turtle OTO writes, one statement per line; or a CSV or JSON vocabulary), from the documents via the interview, or by interview alone; `oto status` lists the four when none is declared. This package diffs it against the last accepted version, counts what a change breaks, checks domain and range conformance, proposes honest widenings, and reports who confirmed each class. |
| Capture | `oto capture` | [capture.py](../oto/capture.py) | What someone said in conversation becomes a dated, attributed source document in the inbox, with the statements in the speaker's words, and enters through the same ingest, drafting and gates as a file. The graph then cites it and the speaker is who to ask. |
| Draft | `oto draft` | [draft.py](../oto/draft.py) | Optional, behind the `draft` extra: a model drafts one document's proposal from the drafting rules, the vocabulary, the brief and the whole document, constrained to the proposal's JSON schema, streamed, with Anthropic's refusal fallback on. The file records which model drafted it and is dry-run merged so a person reads the same report any proposal gets. The one model call in OTO; nothing else imports it. |
| Author | `oto curate`, `oto vet` | [curate/](../oto/curate/) | Edits go into a candidate graph. `curate add` merges proposal files (one per document) into it by rule: new ids added, repeated facts gain a source, changed facts refused; `--dry-run` reports the same without writing. `diff` says what promoting it changes and refuses an overwrite with no supersession record. `apply` appends to the ledger what changed and why. `assertions` gives a spoken correction a citable id. `vet` finds citations to documents the corpus no longer holds. |
| Build | `oto build`, `oto clean`, `oto verify` | [validate/preflight.py](../oto/validate/preflight.py), [builder.py](../oto/builder.py), [compile/](../oto/compile/), [targets/](../oto/targets/) | Pre-flight checks the authored inputs. The builder renames the previous output aside and runs four stages; on failure it restores the previous build. |
| Serve | `oto query`, `oto serve` | [serve/engine.py](../oto/serve/engine.py), [serve/store.py](../oto/serve/store.py), [serve/http.py](../oto/serve/http.py) | Answers seventeen `kg_*` tools over JSON-RPC 2.0 on stdio, over HTTP (`--http`, the same messages on `POST /rpc`, one GET route per tool, `/api/graph` as the whole graph as data, and a view mounted at `/`), or one query per CLI call, from one store interface with two implementations: the SQLite build loaded into memory, the file released so a rebuild can swap it; or a self-hosted Neo4j, the production backend, a live connection checked at startup. The same queries through both must give the same text, and a test proves it. `kg_overview` is the map for a question that starts from no entity; the store carries the recent ledger so it can say what changed without reading a file. A synthesis over it is the query-knowledge skill's job, labelled and cited; readings worth keeping live as authored theme notes under `notes/themes/`. |
| Measure | `oto bench`, `oto bench add`, `oto feedback` | [bench/](../oto/bench/) | Runs a gold question set through the graph engine, a lexical baseline and an optional dense baseline. `add` appends a document's questions with their provenance; a reader's complaint about an answer can be promoted into the set. |

Every command is one module under [cli/](../oto/cli/), named after the command. `oto status` reads
the project and names the next step in this order, which is how the playbooks route.

## The judgment steps, and the skills that carry them

Three steps need a reader: deciding what the corpus must answer, deciding the vocabulary, and
stating which facts each document asserts. The code makes those steps safe rather than automatic.
The playbooks under [skills/](../skills/) run them with an agent, and stop for a person at the
gates. [build-knowledge-base](../skills/build-knowledge-base/SKILL.md) is the end-to-end path; the
others are its steps: the interview, curation, provenance vetting, querying, evaluation,
capture, which is how a conversation becomes a source, and [spec](../skills/spec/SKILL.md), the
downstream use: a product spec or decision record drawn from the graph with every claim cited,
whose decisions go back into it as `DecisionRecord` facts under
[a convention](../skills/spec/references/decisions.md). Beside them,
[concierge](../skills/concierge/SKILL.md) does no task: it reads `oto status`, explains the
station the project is at, offers the options at the fork in front of the person, prints the
recorded reason behind a class, a rule or a change (`oto ontology rationale`, `oto rules
explain`, the ledger), and names the playbook to load. It quotes commands rather than restating
them, and a test fails the build when it names a command the engine lacks or when `oto status`
can suggest a step the skill does not know. An ontology may carry a `guide.md`, what its domain's
graph is for and how to read it, installed as `GUIDE.md` and quoted by the concierge.
[act](../skills/act/SKILL.md) is the protocol for the graph's hands: list the actions the graph
declares, confirm by name before anything that changes the world, invoke through the declared
transport with the agent's own tools, record the response as evidence. The
`.claude-plugin/` manifest and the `.claude/skills/` links make them discoverable by Claude Code;
`.mcp.json` registers the query server for the open project and `hooks/hooks.json` reports the
project's state at session start.

## The compile stages

Each stage is a module with one function, `run(project)`. It asks the project where to read and
write, and never derives a path from its own location or carries a default vocabulary.

| Order | Module | Reads | Writes |
|---|---|---|---|
| 1 | [compile/knowledge.py](../oto/compile/knowledge.py) | `graph.json`, and `ontology.config.json` for the IRIs and attribute types of the triples | `knowledge-graph.json`, `entity-index.json`, N-Triples and the same triples as `graph.ttl` (instances typed with `rdf:type`, their labels in every language as `skos:prefLabel`, aliases and lexicon phrases as `skos:altLabel`, attributes and summaries as typed values), two CSVs, one entity page per node |
| 2 | [compile/rules.py](../oto/compile/rules.py) | `knowledge-graph.json`, `rules.json` | `derived.json`: derived edges and attributes with rule, premises and depth; policy findings. Skipped with a note when no rules are declared. |
| 3 | [compile/ontology.py](../oto/compile/ontology.py) | `ontology.config.json`, `knowledge-graph.json` | `ontology.md`, Turtle, JSON-LD context, every term under the IRI the N-Triples use, with its labels (`skos:prefLabel`, `skos:altLabel`), definition (`skos:definition`), scope note and example, its inverse declared as a property with its own label, and the recorded reasoning as `meta:question`, `meta:rationale`, `meta:alternatives`, `meta:validatedBy` (`https://cynergis.ai/ont/meta#`); the declared shapes and the policy rules as SHACL (`sh:NodeShape`, `sh:property`, `sh:sparql`); `questions.yaml`, every competency question rendered as SPARQL over `graph.ttl` ([compile/sparql.py](../oto/compile/sparql.py)). Reports any type or relation the vocabulary does not declare. |
| 4 | [compile/semantic.py](../oto/compile/semantic.py) | `knowledge-graph.json` | one retrieval card per node, with neighbour context inlined so a thematic search hits the right entity |
| 5 | [targets/sqlite.py](../oto/targets/sqlite.py) | `knowledge-graph.json`, `derived.json`, the indexed directories ([targets/rows.py](../oto/targets/rows.py)), `lexicon.json`, the ledger, the vocabulary and its rationale (a `terms` table, so `kg_define` and every card answer without the project beside the store) | `<slug>.db` with FTS5 tables, built as `.db.new` and renamed into place |
| 7, when targeted | [targets/site.py](../oto/targets/site.py) | the SQLite store, a view directory | `build/site/`: `data.json`, the graph payload `/api/graph` serves (`serve/payload.py`), and the app's files copied beside it, for hosting anywhere static; `oto publish --site` carries it into the query repository |
| 6, when configured | [targets/neo4j.py](../oto/targets/neo4j.py) | the same inputs as stage 5 | the graph in a self-hosted Neo4j: entities labelled by class with typed attributes, relations, evidence and source nodes, derived facts marked, findings, and everything serving reads besides (passages with a full-text index, lexicon rows, the ledger, the schema version); the previous load retired once the new one is in; `--verify` reads it back |

The stages are deterministic: the same inputs produce the same bytes, and a test asserts that a
clean-then-build round trip reproduces the database exactly.

## What a project holds

```
<root>/
  project.config.json     identity: slug, name, namespace, database name
  ontology.config.json    the vocabulary, every declaration an object: classes {definition},
                          properties {domain, range, inverse, definition}, attributes per class
                          {type, definition}, the temporal terms {type, definition}; on any of them
                          a label, alt_labels, a scope_note and an example (a text is one string,
                          or a map of language to string; `languages` lists them, the first the
                          default), on a property an inverse_label; on a class `subclass_of`
                          (the classes it is a kind of), on a property `subproperty_of`; `schemes`:
                          the controlled values, each concept with a label, a definition and a
                          `broader` concept, taken by an attribute of type `scheme:<Name>` (an
                          `enum:a|b` is a scheme whose values carry nothing but their key); and
                          `namespaces`: which ontology each term came from, and so its IRI. A
                          term with no written label is read by its name: part_of as "part of"
  ontology.rationale.json why each class exists and who confirmed it (optional, reviewable)
  rules.json              rules over the graph: derive (positive patterns) and policy (may negate)
  questions.json          competency questions that run: what the graph exists to answer, in the rules' pattern language
  ontology.lock.json      the last accepted vocabulary and rules, written by `oto ontology accept`
  graph.json              the curated graph: the source of truth
  graph.candidate.json    an open `oto curate` session, if any
  proposals/              one file of proposed nodes and edges per source document (authored)
  actions/                one file per action: what can be done about an entity, in MCP tool
                          shape, bound to the graph; becomes an Action node at build (authored)
  assertions.jsonl        append-only log of things people said, citable as sources
  changelog.jsonl         append-only ledger: one entry per apply, with what was retired and why
  lexicon.json            optional: {"entries": [{"term", "aka": [...], "targets": [node ids], "status", "note"}]}
                          so a question in the reader's words resolves to an entity
  gold/questions.jsonl    the benchmark question set, with its own provenance
  feedback.jsonl          what readers said about answers
  notes/                  AUTHORED narrative markdown, indexed alongside the corpus
  notes/themes/           authored readings of the graph, dated, each naming the facts it rests on
  inbox/                  raw sources, unclaimed
  processing/             claimed by an ingest run and extracted; the graph does not hold them yet
  errors/<run>/           files a run could not extract, each with a .error.json beside it
  archive/                the graph holds them; only `oto ingest complete` moves files here
  runs/                   one manifest per run: files, content hashes, outcomes; index.json
  build/                  GENERATED. `oto clean` deletes it whole.
    documents/            the corpus, extracted to Markdown
    entities/  cards/  ontology/  graph/  <slug>.db
```

[project.py](../oto/project.py) resolves the identity and the graph path. [layout.py](../oto/layout.py)
resolves every generated path and says which directories the build owns. This is the only layout,
and `oto init` creates it. The pre-OTO layout, which mixed authored and generated files, was read
through a `--legacy` flag until it had no users left; a project from that time is moved once with
`oto init` and a copy of its graph.

## How a raw file moves

A file is in exactly one place at any moment, and the place says what happened to it.

```
  inbox/ ──claim──► processing/ ──extract ok──► (stays) ──complete──► archive/
                        │                                              archive/<run>/  a new version
                        └──extract fails──► errors/<run>/  + <file>.error.json
```

Claiming is a rename, so a crash leaves nothing half-moved; re-running the ingest claims the
leftovers again, because extraction is idempotent. A lock in `processing/` keeps runs serial.
`complete` refuses while a curate candidate is open or the build predates the run's documents, so
`archive/` always means "in the graph", and an empty `processing/` means nothing is owed. Each run's
manifest records every file's content hash; the same filename arriving with different bytes is
announced as a new version, because the facts citing the old one may need supersession.

## A project as a repository

`oto init --repo` lays a project out to live on GitHub. It adds an `.mcp.json` so Claude Code has
the query tools when it opens the repository, a `CLAUDE.md` saying what the repository is and what
the rule is, and six workflows:

| Workflow | Trigger | What it does |
|---|---|---|
| `oto-ingest` | a push to `inbox/` | claims the inbox into a run, extracts, commits the outcome, opens an issue for what it could not extract |
| `oto-author` | after a successful ingest | an agent, running the Claude Code Action with this engine's plugin, drafts the run's proposals on a branch `oto/run-<id>`, applies them through the curate gates with a ledger note, builds, evaluates, and writes `runs/<id>.report.md`; the workflow commits the branch and opens a pull request with that report as its description, labelled `blocked` if the agent stopped |
| `oto-checks` | a pull request | the gates as status checks: status, candidate check, pre-flight and build, vocabulary, gold set, provenance |
| `oto-review` | `@claude` in a pull request comment | the same agent revises on the branch and pushes; the checks run again |
| `oto-deploy` | a merge to `main` | builds the store and keeps it |
| `oto-actions` | a daily cron | invokes the due read-only actions through the script under `.github/scripts/` (the caller, never OTO), records the responses, takes the proposals through the gates and opens a pull request |

The corpus under `build/documents/` is committed in a repository, because it is an input to the
build and to every review. Nothing reaches `graph.json` on `main` except through a pull request:
that is the human gate in this mode, and every confirmation a playbook would ask a person for is a
section of the report the pull request carries. The unattended rules the agent follows are in
[pipeline-run.md](../skills/build-knowledge-base/references/pipeline-run.md). The authoring and
review workflows need the repository secret `ANTHROPIC_API_KEY`; `OTO_MODEL` and `OTO_ENGINE` are
optional repository variables.

Everywhere, the engine installs from its git repository rather than being assumed on a PATH: `uvx`
on a machine, `pip` in a workflow, one URL in [repo.py](../oto/repo.py) overridable with `--engine`
or the repository variable `OTO_ENGINE`.

The deploy workflow has two targets. The self-hosted Neo4j is the production store (below). The
query repository, when the repository variable `OTO_QUERY_REPO` names one and the secret
`OTO_QUERY_REPO_TOKEN` can write to it (and the static site beside it when `OTO_SITE_VIEW` names
a view), receives the built SQLite store on every merge through
`oto publish` ([publish.py](../oto/publish.py)): the database, the project's identity marked
`store_only`, a manifest with the build sequence, hash and source commit, and a README. Readers
need access to that repository and not to the documents. `oto sync --repo <it>` clones or
fast-forwards it into the store's cache directory (`~/.<slug>-kg`, or `--dest`), and `oto serve`,
`oto query` and `oto status` recognise such a checkout and serve it under the project's own server
name. This is the offline and fallback path beside Neo4j: the two stores answer alike, so a reader
who cannot reach the database loses freshness and nothing else. Git is the transport; the token
lives in the environment for the length of the call and is never written or printed.

## Neo4j, the production store

The engine reads through one interface, `Store` in [serve/store.py](../oto/serve/store.py), and
the answer text is built from the rows it returns. `SqliteStore` is the development store, the
plugin's store on every machine, and the fallback: the build's `.db`, loaded into memory.
`Neo4jStore` is the production store: a live connection to a self-hosted Neo4j that the build
loads and that one server, or many, can share. `tests/test_store_equivalence.py` builds one
project into both, runs every tool through each, and diffs the text; passage search is the one
tool allowed to differ, because FTS5 and Lucene tokenize differently, and its result sets must
overlap instead.

A project chooses with `"serve": {"backend": "neo4j"}` in `project.config.json`; `oto serve
--backend` and `OTO_STORE` override it per process. With Neo4j the engine verifies the
connection at startup, checks that the database holds a load of this project at a schema it
understands, and says which it is serving on stderr. If the database is unreachable it keeps
running, answers every call with the reason, and retries on the next call; it never falls back
to the local file on its own, because a production server that silently answered from a stale
copy would be worse than an honest error. Pre-flight refuses the combination "serve from Neo4j,
never load it", and `oto status` reports whether Neo4j is reachable and loaded.

The load itself runs when the project sets `"targets": ["sqlite", "neo4j"]` and `"neo4j": {"uri":
..., "database": ...}`, with `NEO4J_USER` and `NEO4J_PASSWORD` in the environment (`NEO4J_URI`
overrides the uri, so CI and production can point one config at different servers). It writes
`(:Entity:<Class>)` nodes keyed `<project>:<id>`, so several projects share one database, with
declared attributes in their types and the authored attributes as JSON text beside them;
relationships named after the relations with `kind` asserted or derived; `SUPERSEDES` between
versions; `:Evidence`, `:Source`, `:DerivedAttribute` and `:PolicyFinding` nodes; and the rows
serving needs that are not graph: `:Passage` with a full-text index, `:Lexicon`, `:Changelog`, and
`:OtoProject` carrying the build sequence and schema version. Every element carries the load's
number; once the new facts are in, the previous load's are deleted, so a fact retired in the graph
is retired in Neo4j. `oto build --target neo4j --verify` forces the load and compares the database
with the build. The driver is the `neo4j` extra; the base install never imports it. Cypher, the
full-text indexes and the Graph Data Science library are then available to any other tool.

## The HTTP front end and the graph as data

`oto serve --http [host:]port` puts the engine behind a threaded stdlib `http.server` on the same
store: `POST /rpc` takes the JSON-RPC messages stdio takes and `engine.respond` answers both, so
the two transports cannot disagree and a test proves it byte for byte; `GET /api/<tool>` answers
one tool from its query string with the text and, where the store has them, the rows behind it;
`GET /api/graph` is the whole graph as data, built by [serve/payload.py](../oto/serve/payload.py)
through the store interface, so it holds nothing an agent could not be told and both stores
produce it identically (the equivalence battery compares it); `/api/status` and `/api/changes`
say what is served and whether it moved, for an app that polls. With `--view <name|dir>` an app
ontology is served at `/`, which is how a web app reads the graph live; the `site` build stage
writes the same payload and the same app into `build/site/` for static hosting. No route writes.

Beyond one machine, the rules are few and firm. The server binds to localhost unless a host is
given, and any other host requires `OTO_SERVE_TOKEN` in the environment or the server refuses to
start, saying so. With a token, every call must carry it as `Authorization: Bearer <token>`; a
browser that opens the app carries it once, as `/?oto_token=<token>`, and gets an HttpOnly cookie
and a redirect to the plain address, so the token never sits in the page's URL. The token is
compared in constant time, never written to a file, and replaced in the server's log. Cross-origin
calls are refused unless `--cors <origin>` names the origin (`*` for any), for a hosted app
calling a separate server, and then the preflight allows the bearer header. Neo4j credentials
stay in the server process. In repository mode the deploy workflow publishes the static site
beside the store when the repository variable `OTO_SITE_VIEW` names a view.

## The pending lane, the preview and watch mode

Knowledge is visible the moment it is captured, labelled by where it stands, and never mixed
with what is believed. [curate/pending.py](../oto/curate/pending.py) reads the stations on disk:
files in `inbox/`, documents in `processing/`, every proposal under `proposals/` merged the way
`curate add --dry-run` would (on top of the open candidate, in file order, a refused proposal
listed with its reason rather than dropped), and the candidate's changes against the live graph
(new, changed, updated, retired). The thirteenth tool, `kg_pending`, and `oto query pending`
list it by station; the payload carries the same rows under `pending`, so the explorer draws a
pending entity dotted with its station badge and a pending edge dotted, the reader lists them on
the home page and on the page they would change, and a custom app projects them with `$pending`.

Three regimes decide when a served view moves. **Live**, the default: the view shows the believed
graph and changes only when a candidate is applied and built (in repository mode, when the pull
request merges and deploys); the lane shows what is coming. **Preview**, on command: `oto
preview` composes the live graph, the candidate and every proposal and runs the compile stages
over the result into `build/preview/`, a second store beside the live one, so derived facts and
policy findings for pending knowledge appear; `oto serve --http --preview` serves it. **Watch**,
on every change: `oto serve --http --watch` rebuilds the preview a moment after any authored
file changes ([preview.py](../oto/preview.py)) and the view refreshes through the change signal
it already polls, which now carries a token that moves on a rebuild as well as on a build. The
live store, the candidate and the proposals are never written by any of this. Every payload and
`/api/status` carry a `mode` block (regime, when the preview was built, how many facts differ,
rebuild count), and both built-in apps say it in their header.

## Views: a web app the user passes, fed by the graph

A view is a directory of static files that renders data it does not produce, plus
`app.json` ([apps/manifest.py](../oto/apps/manifest.py)): what the app is, its entry file, the
data files it wants and in which shape, an optional `adapter.js`, and `requires`, the classes,
relations and attributes it expects the vocabulary to declare. Each data file is described in
the projection language ([apps/projection.py](../oto/apps/projection.py)): JSON, evaluated by
the engine over the graph payload, so it is inspectable, testable without a browser, and the same
live and static. `$nodes` with `$where`, `$sort`, `$limit`, `$history` and `$map`; field paths
such as `$label` and `$attr.<name>`; `$out` and `$in` across relations with `$select` and
`$derived` include, exclude or mark; `$evidence`; `$first`, `$count`, `$group`; `$lexicon`,
`$documents`, `$findings`, `$ledger`, `$edges`, `$pending`; `$const`, `$concat`, `$format`;
`$include` for a projection kept in its own file. Formats are `js-globals` (`window.X = ...;`),
`json` and `js-module`; an app with no data entry calls the HTTP routes itself and cannot be
exported, since a static site needs its data on disk.

An app is found by path or by name: `<project>/views/<name>`, `views/` of any ontology on the
machine, or the engine's own `oto/ui/`. An ontology ships apps under `views/`; the
composition carries them, the self-check validates each against the ontology's own vocabulary
(a class or relation a projection names must exist, and `requires` must hold), `oto ontology
show` lists them, and `oto init` installs them into the project. Serving and exporting refuse a
project whose vocabulary lacks what the app requires, naming what is missing, rather than render
an empty page. Three fixture apps of deliberately different shapes, under `tests/fixtures/apps/`,
with their expected output checked in, keep the contract from becoming any one app's shape.

The engine ships two apps and uses the first when none is named, for `oto serve --http` and for
the site stage alike.

The **explorer**, under [ui/explorer/](../oto/ui/explorer/), is the generic view for every
ontology: the graph as a columnar canvas, one column per class in the vocabulary's own order,
a legend of class chips that filter, hover to light a neighbourhood, click for a detail panel
with the entity's provenance line, attributes, evidence quotes, its connections grouped by
relation with an incoming edge named by the inverse the vocabulary declares, a derived edge
marked by its rule with its premises, and history. A dashed node cites no evidence; a dashed
edge was derived. Above a threshold of entities it switches to focus mode and draws the
neighbourhood of a searched or selected entity, hop by hop. It is ported from the Ascent
prototype's reusable graph explorer and made vocabulary-driven: the columns, the palette and
what counts as evidenceable are derived in `defaults.js`, and an ontology or a project may tune
them with a `views/explorer.json` (columns, colours, icons, evidenceable classes, threshold,
title), which the app's manifest names under `overrides` and the engine serves and exports
beside the app when present. It needs React and React Flow, so its source lives in
[ui-src/explorer/](../ui-src/explorer/) with one esbuild step (`npm run build` in `ui-src/`)
and the built bundle is committed, so a user installs nothing and the app makes no network call
beyond the engine. Its pure modules, the payload adapter and the defaults, are tested under Node.

The **reader**, under [ui/reader/](../oto/ui/reader/), is the page-shaped alternative,
served with `--view reader`. It is plain HTML, CSS
and JavaScript with no build toolchain and no network beyond the engine, and its `app.json`
asks for the whole payload as `data.json` (`{"$graph": true}`), so a static export needs nothing
the site stage does not already write. Seven pages behind hash routes: home as the map (counts,
classes, the most connected entities, recent changes, the corpus frontier, the pending count
when the lane is on), a section per class, the entity card with provenance, aliases, attributes
typed and derived, relations grouped by name with derived ones marked and their premises
expandable, history, findings, sources and evidence quotes, the document page with its passage
and everything that cites it, search over entities and passages, findings and rules, and the
ledger. Both themes, phone width, no external font. In live mode it polls `/api/changes` and
reloads on a new build; opened from disk it says "static". Its pure functions (indexing, search,
each page's markup) are exported and tested under Node over a real payload, and a Python smoke
test serves it and exports it.

A domain's own app is attached the same way either built-in is chosen: `--view <name|dir>`, with
the app under the ontology's or the project's `views/`, and served live or exported static.

No shipped ontology carries an app yet: a generic view that applies to every ontology is
planned, and a domain's own app is written against the contract above and shipped under its
ontology's `views/`.

## Ontologies: the unit a project starts from

An ontology is a directory: the vocabulary, its rationale, rules, its competency questions
(`questions.json`, merged by id like rules, installed with the project, carried by an export with
`validated_by` blanked), a sample graph and a README, and optionally a seed lexicon, the interview questions for the domain, a guide to reading the
domain's graph (installed as `GUIDE.md`, quoted by the concierge skill), the actions the domain
declares (`actions/<id>.json`, merged by id with the extender's winning, checked against the
composed vocabulary and the sample, installed as the project's `actions/`), gold question
patterns, and a manifest, `manifest.json`, that names it, versions it, states its `namespace` and
says what it `extends`. A directory without a manifest, or whose manifest states no namespace, is
not usable, and the self-check says so. [model/ontology_manifest.py](../oto/model/ontology_manifest.py) reads and checks
the manifest; [model/ontology_compose.py](../oto/model/ontology_compose.py) resolves `extends`
(bases first, each once, cycles refused) and applies the parts in order: the extender wins a
class description or an attribute type and the report says so, it may widen a relation's domain
or range and never narrow it, rules merge by id and one id means one rule, the rationale of an
inherited class stays the declaring ontology's, samples merge by node id, and the temporal
vocabulary comes from the first part that declares it and is never merged. `ontologies.load`
returns the composed form, which is what a project gets; `load_raw` an ontology's own files.

The questions are the ontology's contract, and the self-check holds it to them: every class,
relation and attribute of the composed vocabulary must be cited by a question that runs (its
patterns, its parameters, or its `terms` list), and the composed sample must answer every
question it must (a `non_empty` gate for every entity of its parameter's class; no row for an
`empty` gate). An ontology that fails either is not usable, so a shipped ontology cannot carry a
term nobody can say the purpose of. The synthetic sample an export invents exercises every
declared pair of domain and range, with a twin example for a relation from a class to itself,
so an exported ontology answers its own questions; a real-data sample that cannot is reported.
In a project, `oto ontology check` prints the questions the live graph cannot answer and the
terms no question cites (errors under `--strict`), diffs the questions against the lock (removed
or a changed `ask`, `params` or `gate`: breaking; added: additive; reworded: cosmetic), and `oto
ontology accept` refuses a vocabulary its questions do not cover. `oto ontology diff` reports
the upstream ontology's question changes beside its vocabulary and rule changes.

A manifest states a `namespace`, the IRI the ontology's own terms live under. Composition
records, in the vocabulary's `namespaces` section, which terms each part brought, a term
belonging to the first part that declares it
([model/namespaces.py](../oto/model/namespaces.py)). The RDF export reads that section and
nothing else, so `auto-claims`' `Claim` is one IRI in every project that uses it, on any machine.
A term no part claims is the project's own and lives under the project's namespace:
`<namespace>ont/`, beside its instances under `<namespace>id/`. `oto ontology export` gives the
new ontology that same namespace, so a term keeps the IRI it already had.

The shipped ontologies extend `oto-core`, which holds the temporal fields and `Document`, the
class every fact cites. Three of them form one chain, the levels of a product's knowledge:
`product` (what it must do, for whom, why) → `software-architecture` (the estate that satisfies
it) → `ddd` (the model the builder works from). A pack sits on the level below it and widens
its relations (`part_of`, `owned_by`, `about`, `satisfies`, `serves`) rather than redeclaring
its classes, so a project composing `product-report` and `ddd` has one `Requirement`, one
`Decision`, one `Team`; where two sibling packs widen the same relation, a merge keeps the
union of both signatures and reports it. `oto ontology show <name>` prints an ontology's manifest, its
composition and what the composition changed, and the self-check, which now covers the manifest,
the optional files, and publishability: deny terms from `OTO_DENY_TERMS` found in any part, or
personal data in the sample, make an ontology unusable. `oto init` records in `project.config.json`
which ontology and release the project started from (and the pack, when it came from one), and installs the lexicon seed, the
interview (`INTERVIEW.md`) and the gold patterns beside the vocabulary.

A registry distributes ontologies: a git repository with an index, `registry.json`, and usually
the ontologies beside it, private or public
([model/registry.py](../oto/model/registry.py)). `oto registry add
<url>` fetches the index and records the registry in `~/.oto/registries.json`
(`OTO_REGISTRIES` overrides) with a cached copy of the index, so `oto ontology` lists what a
registry offers without touching the network again. `oto ontology add <name>` fetches an
ontology into the user directory beside exports, with its provenance (registry, source, ref,
commit) written into its manifest, so it works offline afterwards and `oto ontology update`
knows where to look. A name resolves in this order: an explicit path, the user directory,
the registries in the order they were added, the built-ins. `name@3` pins a version: the
registry's current version comes from its index, an older one from the tag `<name>/v3`.
`oto init` never fetches on its own; it names the registry and the command when an ontology is
only there, and refuses a pin the local copy does not match. `oto registry check` is
the registry's own gate: the index must match the directories beside it. Transport is git, as
for the engine and the query repository; the token `OTO_REGISTRY_TOKEN` goes into an https URL
for the length of a call and nowhere else ([gitx.py](../oto/gitx.py)).

`oto ontology publish --to <registry url>` puts an ontology into a registry: exported from the
project (`--name`, `--summary`, `--from-graph`) or copied from this machine (`--ontology`). It
bumps the version past what the index holds, writes the changelog entry (`--note`) on top of the
registry's own history of that ontology, runs the self-check with the registry checkout as a
root so siblings it extends resolve, regenerates the index, checks the index against the
directories, commits, tags `<name>/v<version>` and pushes; on any problem nothing is pushed. A
registry that is registered on this machine has its cached index refreshed. `oto ontology diff
--project <root>` reads the project's recorded ontology, fetches the upstream current version,
and compares it with the version the project started from (the tag) or, when no tag exists, with
the project's lock: changes with the same severities as `oto ontology check`, each with how many
of this project's nodes or edges it touches, rule ids added, removed or changed, and the
changelog entries the project has not seen. It never writes. `oto status` prints one line when a
newer version is known from the local cache or the engine's shipped copy.

The first publish into an empty repository also writes the registry's README and its check
workflow, which runs `oto registry check`, every ontology's self-check and every pack's check on
each push. This is [the plan](plans/template-registry.md), delivered, in the words of
[the ontology plan](plans/ontology.md).

An ontology declares a `domain`, one lowercase slug: the category it belongs to, for grouping a
listing or a catalog, never the artefact's name (a relation's domain and range live inside the
vocabulary and keep their names). The engine notes a domain it has not seen and never refuses one.

## Packs: the extension a person installs

A pack is the whole thing a person installs into Claude Code
([model/packs.py](../oto/model/packs.py), the plan in [plans/packs.md](plans/packs.md)): one
ontology, the skills that know how to use it, the views that show its graph, and the plugin
manifest Claude Code reads. The ontology is embedded under `ontology/<name>/` with every ontology
it extends beside it, a copy with where it came from recorded, so a pack composes with nothing
else on the machine and the engine can still say when the registry holds a newer release of it.
`oto pack new <name> --ontology <name>` scaffolds one under `~/.oto/packs/` (`OTO_PACKS`
overrides); `oto pack check` validates the manifest, the embedded ontology, every view against
its vocabulary, the skills and the plugin manifest, and runs the publishability scan; `oto pack
refresh` re-embeds the ontology at its current release and regenerates the generated files. The
generated files are `.claude-plugin/plugin.json`, whose version is `<release>.0.0` and which
depends on the engine plugin `oto`, and the skill `start`, which tells an agent to run
`oto init --pack "${CLAUDE_PLUGIN_ROOT}"`: Claude Code substitutes the installed plugin's
directory, so a project starts from a pack with nothing fetched.

`oto init --pack <name|dir>` installs the pack's ontology (its origin kept in the project's
record, and the pack named beside it, so `oto status` and `oto ontology diff` still work) and
copies its views under `<project>/views/`. A view by name is also found under the packs on this
machine.

A registry lists packs beside ontologies, under `packs/<name>` because a pack and its ontology
usually share a name: `oto pack list|show|add|update` mirror the ontology verbs, and `oto pack
publish --to <registry>` copies the pack in, bumps its release, regenerates the plugin files so
the plugin version follows, updates the index and the marketplace, and tags
`<name>--v<release>.0.0`, the convention Claude Code uses to resolve plugin versions. The
marketplace, `.claude-plugin/marketplace.json`, lists the engine plugin first, as a GitHub source
from the engine the registry records, then every pack, so `/plugin marketplace add <registry>`
then `/plugin install <pack>@<registry>` installs a pack and the engine with it, and a pack's
dependency on `oto` resolves inside the same marketplace.

The catalog ([catalog.py](../oto/catalog.py)) is how a person browses before installing:
`oto registry site` in a registry checkout writes a static site, one page for the registry with
packs and ontologies grouped by domain, one page per pack (install lines, the classes with the
question each answers and why it exists, the relations, the actions, the skills, the views, the
guide, the changelog) and one per ontology. A pack's page draws its sample graph with the
explorer: a throwaway project is started from the pack, built, and exported as the explorer's
static site under the page. The registry's site workflow, written with the check workflow when a
registry is created, generates it on every push and publishes it with GitHub Pages; the site
directory is ignored by git.

## Rules, and what a derived fact is

A rule is declared like a class, with a reason and a place for who confirmed it, and versioned in
the same lock. `derive` rules are positive conjunctive patterns over nodes, their declared
attributes and edges, with one action: an edge or an attribute. `policy` rules may negate and
produce findings. A `where` condition may name a declared attribute or one of the node's own
fields (`status`, `as_of`, `valid_from`, `valid_to`, `source_doc`), and a date may be compared
with `$today` or `$today-<n>d`. The rules stage runs forward chaining to a fixpoint over current
facts on every build; a policy also sees `intended` facts, which is how the core's rule
`intended-fact-overdue` flags a plan nobody has checked in ninety days, while a derivation never
rests on one. A derived fact never enters `graph.json`: it lives in `derived.json` and the store, marked
with its rule and its premises, so every answer shows `[derived by <rule>]`, `kg_explain` walks
the chain down to document evidence, and superseding a premise retires the derivation at the next
build. An asserted fact always wins over a derived one. Policy findings appear in `oto curate
check` (blocking or gap by severity), `oto ontology check`, `kg_policy` and the overview.

## Questions that run

A competency question is what the ontology exists to answer, and in OTO it runs. `questions.json`
([reason/questions.py](../oto/reason/questions.py)) declares each one with the sentence a person
would ask, who asks it, why it exists and who confirmed it, and an `ask`: a `when` in the rules'
pattern language (node, edge, `not_edge`, `not_node`, `where`, and `optional`: patterns that
extend a binding when they match and leave their variables unbound when they do not) and a
`select` of bound variables or `var.label`, `var.type`, `var.<attribute>`. A `$NAME` is a
parameter bound to an entity before the patterns run, resolved the way `kg_resolve` resolves a
label; a `where` value may refer to a bound variable (`"$REPORT"`, `"$FIELD.fieldId"`, or spliced
into text) and may test presence (`{"exists": false}`). The `gate` says what an empty
answer means: `non_empty` (the graph must answer; empty is a finding), `empty` (nothing must match;
a row is a finding, the shape of a policy), `any` (informational); a `gaps` pattern runs when the
answer is empty and says why, in words, so an empty answer is never silent. A class pattern covers
the kinds of it, as everywhere else.

The questions ride in the store (a `questions` table, `Question` nodes in Neo4j), so a published
store answers them without its project: `kg_questions` runs every question over the live graph (a
parameterised one for every entity of its first parameter's class) and says which it answers, which
it cannot and why; `kg_ask <id> params` runs one and returns the rows, or the gap. `oto query
questions` and `oto query ask CQ1 SYSTEM="Payments platform"` are the CLI form; `/api/questions` and
`/api/ask?id=CQ1&SYSTEM=...` the HTTP one, with the rows beside the text. A question that cannot
run against the vocabulary (an undeclared class or relation, a parameter nobody declared, a selected
attribute the class does not declare) fails pre-flight and the build, with the reason.
Every shipped ontology ships its questions (`oto-core`'s compose into each extender), and the
self-check holds every ontology to them: see "Ontologies" above.

The build renders each question as SPARQL over `graph.ttl` into `questions.yaml`
([compile/sparql.py](../oto/compile/sparql.py)): `node` is `?x a <C>` (a union, or a class with
kinds, as `VALUES`), `edge` a triple (a union of relations, or a relation with the ones that
specialise it, as `VALUES` on the predicate), `not_edge` and `not_node` are `FILTER NOT EXISTS`,
a `where` is a `FILTER` (a scheme value is its concept IRI, a date is typed), a `$NAME` stays for
the caller to replace with the entity's IRI, every bound node is filtered to current facts, and
`select` binds labels, fields and attributes with `OPTIONAL`. The engine never runs the SPARQL;
a test runs every shipped question both ways, for every entity it can be asked about, and
requires the same rows. What SPARQL cannot read from the export is noted in the file
(`contains` on a list attribute, `$today` rendered as the date of the rendering), and
`graph.ttl` holds asserted facts only: derived facts stay in `derived.json`.

## The capture schema, and proposals from a capture

A tool that interviews people (the PRD & Architecture Studio, or any form) needs to know what to
ask for. Instead of carrying a form of its own, it reads `capture.json`
([compile/capture.py](../oto/compile/capture.py)), rendered from a pack (`oto ontology capture
--from <name>`) or from a project's vocabulary (`oto ontology capture`, and beside
`questions.yaml` on every build): the competency questions grouped by who asks them, each with
its gate and the classes it needs, and one type per class with its fields (typed, enums as
choices, `required`), its links (the relations whose domain covers it, with targets and
cardinality) and what it `requires`. Every field and link carries `x-term`, the IRI it captures.

What the tool collects comes back as a capture: items of a type with a stable id, a label,
fields, links and where in the document it was said. `oto curate propose --from <capture>`
([curate/propose.py](../oto/curate/propose.py)) checks it against the schema, naming an unknown
type, field, link or choice, a missing required field or a link over its `max`, and writes an
ordinary proposal: one node per item (`<class>.<id>`), cited to the document with the section
and the quote as evidence; one edge per link, to another item of the capture or to a node of the
graph. From there `oto curate add` and `oto curate check` apply as to any proposal: the tool
contributes, the gates decide, and nothing is mapped by hand because the terms travelled with
the schema.

## Shapes: the constraints a graph is held to

A shape is declared beside the term it constrains ([reason/shapes.py](../oto/reason/shapes.py)):
a relation's `min` and `max` count what one subject of its domain carries (`"max": 1` on
`charged_to`: a payment is charged to one coverage), an attribute's `"required": true` means every
instance of the class carries a value, a class's `requires` lists the attributes and relations
every instance must carry, and a constraint on a class applies to the kinds of it. A policy rule
is the fourth source of shape and may say which question it protects (`"answers": "SA13"`), so
its finding names what it would leave unanswerable. Tightening a shape is a breaking change in
the lock; loosening one is additive.

The engine evaluates the declared shapes itself, over current facts: `oto curate check` reports
every violation as blocking, beside the required questions the candidate cannot answer, so what
reaches `graph.json` satisfies the vocabulary's contract; `oto ontology check` prints the
declared shapes and the live graph's violations (errors under `--strict`); the self-check holds
an ontology's sample to them, and the synthetic sample an export invents respects every `max`.
The ontology Turtle carries the same constraints as SHACL (`sh:NodeShape` per constrained class,
`sh:property` with `sh:minCount`, `sh:maxCount` and a message; each policy rule as a
`sh:SPARQLConstraint` whose focus node is the rule's first typed variable, with the rule's
severity and the question it answers in the message), the importer reads the property shapes
back (minCount and maxCount only; anything else is noted), and tests with pyshacl require the
SHACL and the engine to find the same violations on the same nodes, for declared shapes and
for policies alike. The engine never reads SHACL to
decide anything; it writes it so that a reader with standard tools checks what OTO checks.

## Actions: the graph's hands, described and never invoked

An action is a file under `actions/`, one per action, in the shape an MCP server describes a
tool (label, description, input schema, annotations) plus what MCP lacks: the class it acts on
(`subject`), how its inputs are filled from the subject's own fields (`bind`), the preconditions
under which it is ready in the rules' pattern language (`when`, whose first pattern binds the
subject), the declared way to invoke it (`invoke`: an MCP server and tool, a CLI command, an
HTTP endpoint or a script path), the names of the environment variables the caller must hold
(`needs`, never values), how a recorded response becomes knowledge (`result`: a document to the
inbox or a proposal), and an optional `schedule`, allowed on a read-only action only.
[actions/model.py](../oto/actions/model.py) reads and checks them; `oto actions check` and
`oto actions list` are the commands. At build time each action becomes an `Action` node whose
source is its file, with an `executed_by` edge to the accountable team; `graph.json` is never
written, and the node carries the whole definition in its attributes, so a store served without
its project still knows the catalog. [actions/catalog.py](../oto/actions/catalog.py)
computes readiness: an action's `when` is matched with the rules' matcher over current and
intended facts, the first pattern binds the subject, and the answer is the action as an MCP tool
definition (name, description, input schema, annotations) plus an `oto` block: the subject class,
the entities it is ready on or why none, the inputs bound from one entity and the ones the caller
must supply, the declared invocation, the variable names it needs, what a recorded result would
assert. The tool `kg_actions` (on both stores, in the equivalence battery, `GET
/api/actions`, `oto query actions`), and `oto actions list [--ready]` / `show <id> --on <entity>`
answer it; the CLI reads the authored graph, the tool reads the store, both through the same
functions. The caller invokes, then hands the response to `oto actions record <id> --on <entity>
--by <who> --response <file>`: [actions/runs.py](../oto/actions/runs.py) writes the run record
under `runs/actions/<id>/<stamp>/` (what was invoked, on what, by whom, when, the bound inputs,
the response and its hash; the names of the variables it needed, never values), the run as a
source document in the inbox, and, for a `proposal` result, the proposal the `then` clause
renders with `$response.<path>` values, evidence pointing at the run document. From there the
ordinary path: `oto ingest` brings the document into the corpus, `oto curate add`, `check`,
`apply` promote the fact, `oto build` compiles it. An intended fact becoming current this way is
a recorded change, not a contradiction; an attribute the graph did not have is added, one whose
value differs is refused at merge and needs supersession. At build each Action node gets an
`acts_on` edge per entity a run touched and its `last_run`, which the catalog, the explorer
and the reader show.

A read-only action may carry a `schedule` (hourly, daily, weekly): it is *due* when it never ran
or its last run is older than the interval, and `oto actions list --due` (and `kg_actions` with
`due`) lists the due ones that are ready on at least one entity. Nothing that changes the world
is ever due. In repository mode `oto init --repo` writes `oto-actions.yml`, a workflow on a
daily cron, and the script it runs, `.github/scripts/oto-actions-invoke.py`: the script is the
caller. It asks OTO what is due, binds the inputs, invokes over the declared transport (`http`
with placeholders URL-encoded and header values that name environment variables taken from the
environment; `cli` with inputs shell-quoted; `script` with the inputs on stdin; `mcp` skipped,
because an MCP tool needs an agent), and records the responses through `oto actions record`.
The workflow then ingests, takes the proposals through the gates, applies when the check is
clean, builds, and opens a pull request: the merge is the human gate. Every variable an action
needs is a repository secret of the same name, listed in the workflow's `env`; values never
reach a record or a log, a missing one skips the action and names it, responses are read up to
a megabyte and a record keeps at most two, a `timeout` on the action bounds the call.

Nothing in the engine executes an action, so the read-only serving invariant holds without
exception. `Action`, `acts_on` and `executed_by` live in
`oto-core`, as does the status `intended`: a fact asserted as a plan and not yet observed, which
the tools print as such, the apps draw dotted, and no "what is" answer includes. The design is
in [plans/actions.md](plans/actions.md).

## What a term is called

Every answer reads the vocabulary as it is labelled: `kg_entity` says `[Component — a part of a
system deployed or released as a unit]`, reads an outgoing edge as `part of → Payments platform`
and an incoming one from this side when the relation declares an inverse, `contains → Payment
API`; the cards under `cards/` and the explorer's edges read the same way. `kg_define <term>`
(also `oto query define`, `GET /api/define`) says what a class, relation or attribute is called
in every language, what it means, its domain, range and inverse, the question it answers, why it
exists, who confirmed it, and how much of the graph uses it; a relation filter (`kg_neighbors`,
`oto query neighbors <term> <relation>`) takes a label as well as a name. The reading comes from
[model/terms.py](../oto/model/terms.py) over the store's term rows, so a published store answers
without the project. A node may carry `labels` (its label per language) and `hidden_labels`
(misspellings and codes, for resolution only, never shown); `kg_resolve` and `kg_entity` match
them, and the lexicon's phrases become the targets' alternative labels in the export.

A class may be a kind of others (`"subclass_of": ["Asset"]`), a relation may specialise one
(`"subproperty_of": "located_at"`), and the engine honours it everywhere a class or relation is
named: `kg_by_type`, `kg_count` and `kg_group_by` on `Asset` cover the components and systems
that are kinds of it and say so; a rule or an action pattern `node: Asset` matches them; a
relation filter covers the relations that specialise it; domain and range conformance accepts a
Component where an Asset is declared; a parent's attribute declarations apply to its kinds. The
closure is computed from the vocabulary each time (`model/vocabulary.py`: `ancestors`, `covers`,
`relation_covers`), never stored. The Turtle writes `rdfs:subClassOf` and `rdfs:subPropertyOf`,
the reference page draws the tree, `kg_entity` says "a kind of Asset" and `kg_define` lists both
directions. A parent that is not declared, or a class that is a kind of itself, fails the gate.
`oto ontology check` sorts a parent added as additive and a parent removed as breaking, counting
the nodes the class covered; it also lists, as RECONFIRM, each class or relation whose definition
changed since the person named in `validated_by` confirmed it, because the lock now carries the
rationale as accepted.

Controlled values are concepts of a scheme: `"state": {"type": "scheme:ClaimState"}` takes the
keys of `schemes.ClaimState.concepts`, each with a label, a definition and optionally a `broader`
concept. An answer shows the value by its concept (`state: Open — Reported and being handled`),
`kg_group_by ... level=top` rolls values up to the top of their broader chain, `kg_define` describes
a scheme with its concepts or a concept with its scheme, and the export writes the scheme as a
`skos:ConceptScheme` with `skos:Concept`s (`skos:inScheme`, `skos:topConceptOf`, `skos:broader`),
the attribute as an object property whose range is the concepts of that scheme, and each value as
its concept IRI. `enum:` stays for values whose meaning needs no words; once a vocabulary declares
`languages`, `oto ontology check` notes each enum. A concept removed is breaking, counted as the
values that use it.

## The shape of a fact

A node carries its type, label, aliases, summary, attributes, tags and sources, plus the temporal
fields that make the graph bi-temporal:

| Field | Meaning |
|---|---|
| `as_of` | when the fact was recorded |
| `valid_from`, `valid_to` | when it was true in the world |
| `status` | `current`, `superseded`, `proposed` or `intended` (asserted as a plan, not observed; never answers "what is") |
| `supersedes`, `superseded_by` | the chain a correction leaves behind |
| `source_doc`, `sources` | the documents or assertions that attest it |
| `attributes` | typed values about the thing. A class may declare them in the vocabulary as `"attributes": {"Claim": {"state": {"type": "enum:open|closed", "definition": "..."}}}` with types string, number, integer, boolean, date, list, enum or `scheme:<Name>` (the concepts of a declared scheme). A present value must fit; a key nobody declared on a declaring class is reported, and refused under `strict_attributes`. Exported as datatype properties. |
| `evidence` | where in the document: `[{"doc", "where", "quote"}]`, shown on the entity page and in every answer |
| `source_type` | `document` (default), `human_assertion`, or `inference` |

A correction never overwrites. It adds a new node, marks the old one superseded, and links the two.
`oto curate check` reports any changed value that lacks that record, a chain that does not point
both ways, a date handoff that does not match, an edge outside its declared domain or range, and a
fact citing a document that has since arrived as a new version and has not been re-attested
against it. The engine answers with current facts by default and slices history on request.

## Where to add things

- **A new source format.** Shipped: text and Markdown, Word, PowerPoint, PDF, Excel, HTML with its
  images, MHTML archives, and legacy Office through LibreOffice. Add a module under
  [intake/extractors/](../oto/intake/extractors/) that
  subclasses `Extractor`, declares its extensions, and returns a `Document`. Register it in the
  extractors package. No core file changes.
- **A new command.** Add `cli/<name>.py` with `cmd_*` handlers and `register(sub)`, then list it in
  `COMMANDS` in [cli/__init__.py](../oto/cli/__init__.py). Use `project_arguments` for the
  `--project` flag.
- **A new compile output.** Add a stage module with `run(project)` and append it to `STAGES` in
  [builder.py](../oto/builder.py). Add every path it writes to `generated_paths`, or the transaction
  cannot restore it.
- **A new query tool.** Add a `*_text` function and a `TOOLS` entry in
  [serve/engine.py](../oto/serve/engine.py). The CLI mode maps a command word to the same function.
- **A new starter vocabulary.** Export one from a project with `oto ontology export`, which
  writes it to `~/.oto/ontologies/<name>/` (or `OTO_ONTOLOGIES`). A user ontology shadows a shipped
  one of the same name, and `oto init --ontology` also accepts a directory path. To ship one with
  the package, add the same four files under [ontologies/](../oto/ontologies/); the ontology test
  takes it through init, build and a query automatically.

## Environment variables

None are needed for ordinary use.

| Variable | What it does |
|---|---|
| `OTO_DB` | Serve a database from an explicit path instead of the project layout. `oto query` sets it. |
| `OTO_PROJECT_CONFIG` | Point the engine at a project config, so a database alone is enough to query. |
| `<SLUG>_DB` | The per-project form of `OTO_DB`, for an installed server. |
| `OTO_STORE` | `sqlite` or `neo4j`: which store the engine serves, over the project's `serve.backend`. `oto serve --backend` sets it. |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (or `NEO4J_AUTH=user/password`) | Where the Neo4j load goes and what serves from it. The uri may also live in the project config; the credentials never do. |
| `OTO_DENY_TERMS` | Terms the publishability gate refuses. See [GATES.md](GATES.md). |
| `OTO_ONTOLOGIES`, `OTO_PACKS`, `OTO_REGISTRIES` | Where user and fetched ontologies and packs live, and the registries file. |
| `OTO_REGISTRY_TOKEN`, `OTO_QUERY_REPO_TOKEN`, `OTO_ENGINE_TOKEN` | Tokens for private ontology registries, the query repository, and the engine repository in workflows. |
| `OTO_SERVE_TOKEN` | The bearer token `oto serve --http` requires from every caller when it is set, and demands before binding beyond localhost. |
| `PYTHON` | Which interpreter `tools/run_gates.sh` uses. |

## Dependencies, on purpose

The compile and serve paths use the standard library only, and CI asserts that a bare install
pulls in nothing. Document parsers live in the `intake` extra, the embedding baseline in `bench`,
and the Anthropic SDK in `draft`, used by `oto draft` alone. The engine must never need a model to
answer a question; a test asserts the SDK is not imported by anything but the drafter.
