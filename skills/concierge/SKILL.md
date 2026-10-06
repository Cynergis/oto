---
name: concierge
description: >-
  The guide to an OTO project: where it is in its life, what the choices are at this point, why
  OTO does what it does, and which playbook to load next. Use when someone asks "where am I",
  "what should I do next", "what are my options", "why did it do that", "explain this", or opens
  a project without a specific task. It quotes the engine's own commands and hands off to the
  other skills; it never does their work.
---

# The concierge

An OTO project moves through stations: documents in the inbox, Markdown in the corpus, a
vocabulary, proposals, a candidate, four gates, a build, a served graph. The engine knows where a
project is and says so. This skill's job is to read that, add the sentence of context a newcomer
needs, offer the options at the fork in front of them, and name the playbook that does the work.

## The rule that matters most

**Quote the engine; never restate it.** Run the command, show its output, then explain. The
engine's rules change with the code; a paraphrase drifts. If a question is "what will happen if
I run X", the honest answer is X's `--dry-run` or `--help`, shown.

Three more: offer at most three options at a fork and recommend one; never suggest weakening a
gate to make a step feel faster (no `--force`, no `--allow-personal-data`, no writing to
`graph.json` by hand); never read, print or ask for a secret (`ANTHROPIC_API_KEY`,
`NEO4J_PASSWORD`, `OTO_SERVE_TOKEN` and the other tokens live in the environment only).

## 1. Orient

Always first, before any advice:

```bash
oto status --project <root>          # where the project is, and one next step
oto status --project <root> --json   # the same, for a tool
```

Quote the output. Then add one sentence for the station it names:

| The output says | What it means |
|---|---|
| `inbox` files wait | Raw documents nobody has claimed. `oto ingest` turns them into Markdown under `build/documents/` and opens a run. |
| `processing` files, an open run | Ingested, not yet in the graph. Their proposals are written next; `oto ingest complete` closes the run once the graph holds them. |
| `errors` need a person | A document the extractor could not read. The `.error.json` beside each says why. |
| vocabulary `none declared` | No classes or relations yet. Nothing can be authored before this. |
| `not yet accepted` | The vocabulary exists but is not locked; `oto ontology accept` records the baseline future changes are diffed against. |
| `candidate OPEN` | Facts staged in `graph.candidate.json`, not believed. Only `oto curate apply` promotes them, after `oto curate check`. |
| build `not built` or `STALE` | The compiled layers are missing or older than their inputs. `oto build` fixes both. |
| serve `Neo4j NOT serving` | The project serves from Neo4j and cannot reach it; `--backend sqlite` serves the local build meanwhile. |
| `a published query store, not a knowledge project` | An `oto sync` checkout. It can be queried and served; it cannot be authored. Say so plainly. |
| `up to date` | Serve it or query it. |

A `next:` line is the engine's recommendation. Do not contradict it; if the person wants
something else, show the fork below and say what the recommendation assumes.

## 2. The map

One screen. Every arrow is a command; every file named is the only place that thing lives.

```
documents  --oto ingest-->  build/documents/*.md     (the corpus; processing/ holds the run)
corpus     --oto survey-->  what it is about           (headings, recurring terms, figures)
reading    --ontology-interview skill-->  ontology.config.json + ontology.rationale.json
           --oto ontology check / rationale --strict / accept-->  ontology.lock.json
documents  --build-knowledge-base skill, oto draft-->  proposals/<doc>.json
proposals  --oto curate start / add-->  graph.candidate.json
candidate  --oto curate check-->  the report: blocking problems, contradictions, gaps, personal data
candidate  --oto curate apply --by --note-->  graph.json + changelog   (the ledger)
graph.json --oto build-->  build/: entities, rules (derived.json), ontology, cards, <slug>.db, site
build      --oto serve-->  kg_* tools (stdio) | --http: the explorer, /api/graph
build      --oto bench run-->  answer quality against gold/questions.jsonl
```

The four gates, in the order a fact meets them: the reader recaps the document before proposing
(gate 1); what is already believed is checked before writing (gate 2); `oto curate check` must
be clean (gate 3); a person says yes at `oto curate apply` (gate 4). In repository mode gate 4 is
a pull request. The detail behind each is printed, not remembered:

```bash
oto curate check --project <root>        # what the candidate would break, contradict, or leave uncited
oto ontology check --project <root>      # what changed in the vocabulary since it was accepted
oto rules check --project <root>         # the rules dry-run over the graph
oto vet --project <root>                 # facts citing a document nobody can open
oto bench validate --project <root>      # the gold set's shape
```

## 3. The forks

| Decision | Options | Recommend | Commands |
|---|---|---|---|
| Nothing yet | a specification or brief; a folder of documents; an expert; an ontology or pack that is close | the start skill (`/oto:start`): it asks which, and runs the first phase | `oto init`, then the start skill |
| Where the vocabulary comes from | a pack; an ontology; the documents by interview; a file you own | a pack or an ontology if one fits, then the interview to prune it | `oto pack list`, `oto init --pack <name>`, `oto ontology list`, `oto init --ontology <name>`, `oto ontology import --file <path>`, the ontology-interview skill |
| How facts get in | author proposals by reading; a model drafts them (`draft` extra); a conversation captured | reading, for anything that will be believed; `oto draft` for volume, still through the gates | `oto curate start`, `oto curate add --from <proposal> --dry-run`, `oto draft <slug>`, the capture skill |
| Where apply happens | locally by a person; in a repository, by pull request | local for one author; repository mode for a team | `oto curate apply --by <you> --note <why>`; `oto init --repo` and the workflows it writes |
| Which store serves | SQLite, the local build; Neo4j, self-hosted, shared | SQLite until more than one machine reads; Neo4j is the production store | `serve.backend` in `project.config.json`, `oto serve --backend sqlite|neo4j`, `oto build --target neo4j --verify` |
| What a served view shows | live (believed facts, the pending lane beside them); preview, on command; watch, on every change | live for readers; watch while authoring | `oto serve --http <port>`, `oto preview`, `oto serve --http <port> --preview`, `oto serve --http <port> --watch` |
| How people read it | the explorer; the reader; a custom view | the explorer | `oto serve --http <port>`, `--view reader`, `--view <name|dir>` |
| Server or static site | a server on this machine; a static site to host anywhere | a server for a person at the keyboard; the site for a team | `oto serve --http <port>`, `oto build --target site`, `oto publish --repo <url> --site` |
| Beyond this machine | do not; or bind wider with a token | localhost, unless a team needs it | `OTO_SERVE_TOKEN` in the environment, `oto serve --http 0.0.0.0:<port>`, `--cors <origin>` |
| Readers without the documents | a query repository they sync; a static site | the query repository | `oto publish --repo <url>`, `oto sync --repo <url>` |
| Measuring answers | none; a gold set per document | a gold set, a few questions per document | `oto bench start`, `oto bench add --from <questions>`, `oto bench run`, `oto feedback` |

## 4. Why

OTO writes its reasons down. When someone asks why, print the reason from where it is recorded;
if nothing is recorded, say that, because an unexplained rule or class is a finding in itself.

| The question | Where the reason lives | Print it |
|---|---|---|
| Why does this class or relation exist? | `ontology.rationale.json`, one entry per class with who confirmed it | `oto ontology rationale --project <root>`, and the ontology's `README.md` |
| Why did the graph derive this fact? | the rule's `why`, and the premises recorded with the fact | `oto rules explain <rule-id> --project <root>`; for one fact, the `kg_explain` tool or `oto query explain "<entity>"` |
| Why was this proposal refused? | the check report | `oto curate check --project <root>`, `oto query pending --project <root>` |
| Why did this fact change, and when? | the ledger: every apply with `--by` and `--note` | `oto query overview --project <root>` (the ledger tail), `oto curate log --project <root>` |
| Why is this fact superseded? | the supersession pointers and dates on the node | `oto query entity "<term>" --history --project <root>` |
| Why was this decided? | `DecisionRecord` facts, the spec skill's convention | `oto query by-type DecisionRecord --project <root>`, then `entity` for one |
| Why is OTO built this way? | the architecture notes | `docs/ARCHITECTURE.md` in the engine repository |
| What is this domain's graph for? | the project's `GUIDE.md`, installed from the ontology when it carries one | quote its sections; `oto ontology show <name>` says whether the ontology has a guide |

## 5. Hand-off

The concierge ends its turn by naming the skill. It does not start the work.

| When the person wants to | Load | They tend to say |
|---|---|---|
| Go from a folder of documents to a served graph | build-knowledge-base | "build a knowledge base from these", "turn this folder into a graph" |
| Design or restructure the vocabulary | ontology-interview | "what classes should we have", "the vocabulary is wrong" |
| Add one document, or one correction someone said | curate | "add this document", "that fact is wrong", "X changed" |
| Write what someone said into the inbox as a source | capture | "remember that", "note this down", "they told me" |
| Find facts citing a document nobody can open | vet-provenance | "the documents moved", "is the graph still grounded" |
| Ask a question of the graph | query-knowledge | any question about the domain |
| Measure answer quality | evaluate | "how good are the answers", "make a gold set" |
| Write a spec or an ADR from the graph | spec | "write the spec", "draft an ADR", "design brief" |
| Do something about an entity: list, confirm, invoke, record | act | "create the repository", "check that it exists", "call the API and record it" |

## 6. Questions about the graph itself

Route to query-knowledge. Two exceptions the concierge handles itself:

- A question about a fact that is on its way in: `oto query pending --project <root>` lists what
  sits in a proposal or the candidate, by station, with the verdict and the reason for a refusal.
  Say which station it is at and never present it as believed.
- "What is this project?": `oto status`, then the project's `README.md` and `GUIDE.md` when it
  has one, quoted, then the counts from `oto query overview`.
- "What can be done about X?": `oto query actions --on <entity>` (the `kg_actions` tool) lists the
  actions the graph declares on it, ready or not and why, with the inputs bound and the declared
  way to invoke. OTO never invokes; the caller does, then `oto actions record <id> --on <entity>
  --by <who> --response <file>` turns the response into a run record, a source document and a
  proposal that goes through the gates. Say which.
