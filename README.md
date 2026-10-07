# OTO

**OTO, Ontology-To-Operations:** from enterprise meaning to running agents. Published by [Cynergis](https://cynergis.ai).

See it running: the [guided demo](https://demo.cynergis.org) walks through the Studio over a knowledge graph OTO built for a sample insurer. The story and the documentation are at [oto.cynergis.org](https://oto.cynergis.org).

> **Names.** The command, the import name and the repository are **`oto`**. The distribution is
> **`oto-kg`**, because `oto` was taken on the package index. Two namespaces, one tool: what you
> type is `oto`.

OTO builds a **temporal knowledge graph** from your own documents and conversations, then serves it
to a natural language agent.

It is domain agnostic. You declare your domain vocabulary in one config file. OTO compiles your
curated graph into a queryable store, and refuses to build if the graph uses vocabulary you did not
declare.

## What makes it different

Most retrieval systems answer "what does a document say". OTO answers **"what is true now"**, and
shows why.

- **Bi-temporal facts.** OTO separates when a fact was recorded from when it was true.
- **Supersession, never overwrite.** A correction retires the old fact and keeps it queryable.
- **Provenance on every fact.** Each node and edge cites its source.
- **An integrity gate.** The build fails on undeclared vocabulary, so the model cannot drift.
- **A versioned vocabulary.** `oto ontology check` says what a schema change breaks, and how many
  nodes and edges it touches, before you ship it. Classes declare typed attributes, so "how many
  open claims" means the same thing on every node.
- **Recorded reasoning.** Every class carries the question it answers and who confirmed it, so the
  model is reviewable and "validated" is a count rather than an opinion.
- **Questions that run.** The competency questions a vocabulary exists to answer are written once,
  in the engine's pattern language, and run: every term must be cited by one, every ontology's
  sample must answer them, `kg_ask` answers one with the rows or the gap, and the build renders
  each as SPARQL so a reader with standard tools asks the same thing.
- **Briefs that block.** What an agent must know before a task is a brief: the questions it must
  be able to answer. `kg_brief implement-step STEP=...` is READY with the facts, or BLOCKED by
  name with the gaps, before a line is written.
- **Shapes that gate.** Cardinality, required attributes and policy rules are declared beside the
  terms, evaluated by the engine before a change enters the graph, and written as SHACL that a
  test holds to the same verdicts.
- **Rules that explain themselves.** Declared rules derive the facts a person would infer and flag
  what a policy forbids. A derived fact is marked in every answer and explained down to the
  documents it rests on; it is never written into the graph.

## Status

Early development. The engine was extracted from a working private system that holds
1,918 nodes and 3,640 edges across about 100 documents, and is developed here.

## Install

The engine is not on a package index; it installs from this repository.

The repository is public: `uvx` and `pip` clone it like any other git dependency, with no
credential. A workflow that installs the engine from a private fork instead sets the secret
`OTO_ENGINE_TOKEN` (see repository mode below).

The extras name what a machine needs beyond the stdlib engine, and they combine inside the
brackets. `all` is every one of them; a machine that only serves needs none.

```bash
# On a machine, with uv installed: run it without installing anything else.
uvx --from "oto-kg @ git+https://github.com/Cynergis/oto" oto --help
uvx --from "oto-kg[all] @ git+https://github.com/Cynergis/oto" oto --help          # every extra
alias oto='uvx --from "oto-kg[all] @ git+https://github.com/Cynergis/oto" oto'     # and keep it

# Or into an environment of your own.
pip install "oto-kg[all] @ git+https://github.com/Cynergis/oto"        # everything below at once
pip install "oto-kg[intake,neo4j] @ git+https://github.com/Cynergis/oto"   # or pick: extras combine
pip install "oto-kg @ git+https://github.com/Cynergis/oto"            # compile and serve (stdlib only)
pip install "oto-kg[intake] @ git+https://github.com/Cynergis/oto"    # add document extraction: Word,
     # PowerPoint, PDF, Excel, HTML, MHTML, text; legacy .doc/.ppt/.xls convert through LibreOffice if present
pip install "oto-kg[draft] @ git+https://github.com/Cynergis/oto"     # `oto draft`: a model drafts a
     # document's proposal for review. The one model call in OTO; the compile and serve paths never make one
pip install "oto-kg[neo4j] @ git+https://github.com/Cynergis/oto"     # the production store: load the
     # built graph into a self-hosted Neo4j and serve from it (serve.backend: neo4j); SQLite stays the
     # development store and the fallback, and the two answer alike
pip install "oto-kg[rdf] @ git+https://github.com/Cynergis/oto"       # `oto ontology import --file`: read a
     # real ontology, OWL, RDFS or SKOS in any RDF syntax, every term keeping its IRI
```

To test everything end to end, in the order a real project goes through it, follow
[docs/E2E-TESTING.md](docs/E2E-TESTING.md): seventeen stages, each with its commands and what pass looks like.

In Claude Code, install the plugin and the engine comes with it: `/plugin marketplace add Cynergis/oto`
then `/plugin install oto@oto`, or `claude --plugin-dir <a clone of this repository>`. The plugin's
server and hook run the engine through `uvx`, so uv is the only prerequisite.

## Getting started

In Claude Code with the plugin, `/oto:start`: it asks what you have (a specification, a folder of
documents, a domain expert, an ontology or pack that is close), gets it in, derives the first
questions for you to confirm, and hands off to the interview. The rest of this section is the
same path by hand.

## From a folder of documents to a served graph

OTO is the deterministic half of that job: extraction, gates, compilation, serving. The other half,
reading the documents, deciding the vocabulary and stating which facts each document asserts, needs
judgment, so it is done by a person or by an agent following the playbook in
[skills/build-knowledge-base](skills/build-knowledge-base/SKILL.md). With Claude Code:

```bash
claude --plugin-dir .          # or open this repository: .claude/skills/ links the same playbooks
# then: "build a knowledge base from the documents in ~/docs/claims"
```

The agent runs the commands below, stops at three gates (the questions and classes, the diff before
apply, and wiring the server), and hands back a graph where every fact cites its document. The
plugin also registers `oto serve` as an MCP server for the open project and runs `oto status` at
session start, so the agent has the query tools and knows where the project stands.

```bash
oto ontology show auto-claims                                          # what an ontology composes
oto registry add https://github.com/Cynergis/oto-registry    # the registry: ontologies and packs; then
oto ontology add <name>                                                # fetch an ontology, and --ontology it
oto pack add <name> && oto init --name "Acme Claims" --pack <name> --project claims   # or a pack: its ontology, skills and views
oto init --name "Acme Claims" --ontology auto-claims --project claims   # or two ontologies, merged
oto init --name "Acme Claims" --ontology auto-claims --project claims --repo   # ...laid out for GitHub:
     # a push to inbox/ ingests, an agent authors on a branch and opens the PR, the PR is the gate
cp ~/docs/claims/* claims/inbox/ && oto ingest --project claims   # claims the inbox into a run
oto survey --project claims             # a map of the corpus: headings, recurring terms, acronyms
oto status --project claims             # no vocabulary yet? it lists the four ways to get one
oto ontology import --project claims --file vocabulary.csv   # ...or bring one you already own
# design or prune the vocabulary from the questions the corpus must answer (ontology-interview skill)
oto curate start --project claims
oto draft handbook --project claims     # optional: a model writes the first draft of a proposal
oto curate add --project claims --from claims/proposals/handbook.json   # one proposal per document
oto curate check --project claims       # blocking problems, contradictions, gaps, personal data
oto curate apply --project claims && oto build --project claims
oto bench add --project claims --from claims/proposals/handbook.questions.json   # evaluate skill
oto ingest complete --project claims    # the graph holds the run: processing/ -> archive/
oto serve --project claims              # eighteen kg_* tools over JSON-RPC 2.0, for an MCP host
oto serve --project claims --http 8765              # the same over HTTP, the graph explorer at /, the whole
     # graph at /api/graph; --view reader for the page-shaped reader; --view <name|dir> serves your own
     # web app instead, its data files generated from the graph as its app.json projections say
oto serve --project claims --http 8765 --watch      # the preview: the graph as it would be with every proposal
     # and the candidate in, rebuilt on each change while you author; --preview builds it once; the live
     # store is never touched, and `oto query pending` lists what is on its way in, by station
oto build --project claims --target site            # or as a static site under build/site/, to host anywhere
OTO_SERVE_TOKEN=... oto serve --project claims --http 0.0.0.0:8765   # beyond this machine only with a token,
     # sent as a bearer header (a browser opens /?oto_token=... once); --cors <origin> for a hosted app
oto status --project claims             # at any point: where the project is, and what comes next
     # or ask the concierge skill: it quotes this, explains the station, offers the options, names the playbook
oto actions list --project claims           # what can be done here: the actions the graph declares, ready on which
     # entities. OTO never invokes; `show <id> --on <entity>` prints the bound invocation for the caller, and
     # `record` turns the caller's response into a run record, a source document and a proposal for the gates
```

## Use

Start from a vocabulary rather than an empty file:

```bash
oto ontology                                        # four starter vocabularies, plus yours
oto init --slug claims --name "Acme Claims" --ontology auto-claims
oto build --project claims                           # it builds as shipped
oto query --project claims entity "Claim C-5001"     # a cited answer, minutes in
```

A vocabulary you designed for one project becomes the starter for the next:

```bash
oto ontology export --project claims --name acme-claims --summary "Claims, as Acme handles them"
oto init --slug claims-eu --name "Acme Claims EU" --ontology acme-claims
```

The export carries the vocabulary and its recorded reasoning, invents a sample graph so nothing
from the source project leaks, and blanks every `validated_by`: a domain expert's confirmation in
one project is not a confirmation in another. It refuses while any class lacks a recorded reason.
Ontologies live in `~/.oto/ontologies/`, and a directory path works too.

A **pack** is what a person installs into Claude Code: one ontology, embedded with what it extends,
the skills that know how to use it, and the views that show its graph. `oto pack new claims
--ontology acme-claims` scaffolds one, `oto pack check` validates it, `oto pack publish --to
<registry>` releases it; the registry is a Claude Code marketplace, so `/plugin marketplace add
Cynergis/oto-registry` then `/plugin install <pack>@cynergis` installs a pack and this engine's
plugin with it, and the pack's `start` skill begins a project from the installed copy. The registry
publishes a catalog with GitHub Pages, one page per pack with its sample graph drawn, to browse
before installing (`oto registry site`).

Or start empty:

```bash
oto init --slug acme --name "Acme Knowledge Base"   # a project holds data only
cp ~/sources/*.md acme/inbox/                       # drop in sources
oto ingest --project acme                           # extract to one format
# declare your vocabulary in ontology.config.json, author graph.json
oto build --project acme                            # compile every layer
oto query --project acme entity "some term"         # ask, with citations and dates
oto serve --project acme                            # or run the query server
oto clean --project acme                            # delete everything generated
oto ontology check --project acme                   # what would a schema change break? which questions go unanswered?
oto query --project acme questions                  # what the graph exists to answer, and whether it does
oto ontology widen --project acme                   # propose honest domain and range declarations
```

Knowledge enters through gates, never by accident:

```bash
oto curate start --project acme     # edits go in a candidate, not the live graph
oto curate check --project acme     # blocking problems, contradictions, gaps, personal data
oto curate apply --project acme     # promote it; `oto curate undo` puts it back
```

`check` reports every changed value that has **no supersession record**. Overwriting destroys the
answer to what was true before, which is the property the whole system exists to protect.

Corrections people make in conversation get the same treatment as documents. The capture skill
writes what was said into the inbox as a dated source, and the pipeline takes it from there:

```bash
oto capture --project acme --title "Deductible change" --by "R. Handler, claims lead" --at 2026-04-01 \
  --statement "The deductible went up in April, not May."
```

A curator working locally can instead record it in the assertions log with `oto curate assert`. Either
way the fact that results cites the statement and names the speaker, and a fact citing an assertion
that is not in the log is a blocking error, which is what makes the citation mean something.

The graph is also what a product spec or an architecture decision is written from. The
[spec](skills/spec/SKILL.md) skill grounds every claim in a cited entity, keeps a mandatory section
for what the graph does not say, and lists the decisions the document makes in a shape the pipeline
turns into `DecisionRecord` facts, so the next spec starts from recorded decisions instead of
re-deciding them.

Serving has two stores that answer alike. The local SQLite build is the development store; a
self-hosted Neo4j (`"serve": {"backend": "neo4j"}`) is the production one, loaded on every merge.
For readers who need answers and not documents, `oto publish` pushes the SQLite store to a
read-only query repository and `oto sync --repo <it>` brings it to a machine, where `oto serve`
serves the checkout:

```bash
oto publish --project acme --repo https://github.com/org/acme-query     # the deploy workflow does this
oto sync --repo https://github.com/org/acme-query                        # on a reader's machine
oto query --project ~/.acme-kg entity "Press 01"
```

Authored and generated files never share a directory:

```
acme/
  ontology.config.json   your vocabulary
  graph.json             the curated graph
  notes/                 AUTHORED narrative, indexed alongside the rest
  inbox/  processing/  errors/  archive/   a raw file is in exactly one of these
  runs/                  one manifest per ingest run, with content hashes
  build/                 GENERATED. `oto clean` deletes it whole.
```

That rule is enforceable because of the split. It was not before: measured on a real project, the
directories called "generated" held 3,847 generated files and 17 authored ones, and a tool that
cleared a directory destroyed authored work.

Raw files move the same way a mail spool does. An ingest run claims the inbox into `processing/`,
failures land in `errors/<run>/` with the reason beside each, and a file reaches `archive/` only
through `oto ingest complete`, which refuses until the graph holds its facts. An empty `processing/`
means nothing is owed. Each run's manifest records content hashes, so the same filename arriving
with different bytes is announced as a new version rather than silently replacing the old corpus.

Answers carry a status, a date and a source, so a claim can be checked:

```
=== Press 01  [Machine]  (m.1) ===
status=current  ·  as_of=2026-01-01  ·  valid_from=2026-01-01  ·  source_doc=handbook
aka: Press One

Relationships (outgoing):
  installed_at → North Plant
```

## Measuring whether the answers are good

```bash
oto bench start --project acme    # start a gold question set
oto bench validate --project acme    # it refuses a set with no recorded provenance
oto bench run --project acme --ablations
```

Every report prints **where the questions came from** before the numbers, and the threats to validity
after them, because context is the first thing lost when a table is pasted into a deck. A
model-authored set must declare what fraction a human checked.

The comparison includes a dense embedding baseline (`pip install 'oto-kg[bench]'`). That is
deliberate: it measures the one dimension where an embedding method usually wins, and a report that
omits its opponent's best case is marketing. If the baseline is unavailable, the report says the lane
is **unmeasured** rather than quietly dropping it.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip   # the pip macOS ships cannot do an editable install
.venv/bin/pip install -e '.[intake,dev]'
PYTHON=.venv/bin/python tools/run_gates.sh      # tests, self-test, ontologies, publishability, syntax
```

The compile path is stdlib-only, so a build needs nothing installed beyond OTO itself. CI asserts
that. See [docs/GATES.md](docs/GATES.md) for the gates and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for how the package is laid out and where to add things. The playbooks under [skills/](skills/)
cover the steps that need judgment: designing a vocabulary, curating, and vetting provenance.

## Contributing, and who we are looking for

OTO is in beta and free while it is. It is Apache-2.0 and stays so. We are looking for
contributors of four kinds:

- **an ontology for a domain you know**: the vocabulary with the question each class answers,
  its rules, a sample, a guide; published to the registry and listed in the catalog;
- **a view**: a web app fed by the graph through the app contract, for a domain or for everyone;
- **a skill**: a playbook an agent follows, for a step that needs judgment;
- **a bug with a document that reproduces it**: the fastest way to make the engine better.

Contributions take a Developer Certificate of Origin sign-off (`git commit -s`), not a licence
agreement; [CONTRIBUTING.md](CONTRIBUTING.md) says how, and the end-to-end journeys in
[docs/E2E-TESTING.md](docs/E2E-TESTING.md) are the fastest way to see what the engine does. The
site is [oto.cynergis.org](https://oto.cynergis.org).

## Licence

Apache-2.0. See [LICENSE](LICENSE).
