---
name: concierge
description: >-
  The guide to an OTO project: where it is in its life, what the choices are at this point, why
  OTO does what it does, and which playbook to load next. Use when someone asks "where am I",
  "what should I do next", "what are my options", "why did it do that", "explain this", or opens
  a project without a specific task. It reads the engine and tells the person in plain words, and
  hands off to the other skills; it never does their work.
---

# The concierge

An OTO project moves through stations: documents in the inbox, Markdown in the corpus, a
vocabulary, proposals, a candidate, four gates, a build, a served graph. The engine knows where a
project is and says so. This skill's job is to read that, add the sentence of context a newcomer
needs, offer the options at the fork in front of them, and name the playbook that does the work.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say question numbers, ids, class or
  field names, file names or commands, and never paste what a command printed.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** where things stand in a sentence or two, the choices in front
  of them (at most three, one recommended), then who takes it from here.

## The rule that matters most

**Read the engine; tell it in plain words.** Run the command yourself and base everything you say on
what it printed, never on memory: the engine's rules change with the code, and a remembered rule
drifts. Then tell the person what it means. Show the output itself only when they ask to see it. If
the question is "what will happen if I do this", run its `--dry-run` or `--help` and say what it
would do.

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

Read the output, and tell the person where the project is in one or two plain sentences; the table
says what each line means (for you):

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
| `packs` lists plugins | The packs and tools this project uses (declared in its `.claude/settings.json`) and the skills each brings: the routes beyond OTO's own skills. `oto status --json` says what each skill does. A plugin marked `NOT INSTALLED` offers nothing here yet: give the install line it prints. |
| `packs none` | The project uses no pack: only OTO's own skills apply until one is declared. |
| a pack marked `(playbook: <skill>)` | The project's journey is that playbook's (`/<pack>:<skill>`): it leads it scene by scene and asks you where the project is. Name it when the person wants to go on with that journey; never run its scenes yourself. |
| a pack marked `(binding of <ontology>)` | Where the product runs and what it is built with is captured with that pack's binding skill (`oto status --json` names it). Before anything is built, deployed or tested end to end, the briefs it brings say what is still missing: say it in plain words, with who can answer it. |

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
build      --oto serve-->  kg_* tools (stdio) | --http: the workbench, /api/graph
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
| Nothing yet | a journey a pack leads from start to end (a product, with its playbook); a specification or brief; a folder of documents; an expert; an ontology or pack that is close | the playbook when one fits what the person wants (`oto pack list --playbooks` says what each is for); otherwise the start skill (`/oto:start`): it asks which, and runs the first phase | `oto pack list --playbooks`, then the playbook's skill; or `oto init`, then the start skill |
| Where the vocabulary comes from | a pack; an ontology; the documents by interview; a file you own | a pack or an ontology if one fits, then the interview to prune it | `oto pack list`, `oto init --pack <name>`, `oto ontology list`, `oto init --ontology <name>`, `oto ontology import --file <path>`, the ontology-interview skill |
| How facts get in | author proposals by reading; a model drafts them (`draft` extra); a conversation captured; an interview against the capture form | reading, for anything that will be believed; `oto draft` for volume, still through the gates | `oto curate start`, `oto curate add --from <proposal> --dry-run`, `oto draft <slug>`, the capture skill, `oto curate propose --from <capture>` and the capture-form skill |
| Where apply happens | locally by a person; in a repository, by pull request | local for one author; repository mode for a team | `oto curate apply --by <you> --note <why>`; `oto init --repo` and the workflows it writes |
| Which store serves | SQLite, the local build; Neo4j, self-hosted, shared | SQLite until more than one machine reads; Neo4j is the production store | `serve.backend` in `project.config.json`, `oto serve --backend sqlite|neo4j`, `oto build --target neo4j --verify` |
| What a served view shows | live (believed facts, the pending lane beside them); preview, on command; watch, on every change | live for readers; watch while authoring | `oto serve --http <port>`, `oto preview`, `oto serve --http <port> --preview`, `oto serve --http <port> --watch` |
| How people read it | the workbench (the graph as pages and as a graph, the ontology, the project); a custom view | the workbench | `oto serve --http <port>`, `--view <name|dir>` |
| Server or static site | a server on this machine; a static site to host anywhere | a server for a person at the keyboard; the site for a team | `oto serve --http <port>`, `oto build --target site`, `oto publish --repo <url> --site` |
| What the data means | a store's catalog introspected in place; its lineage from a dbt manifest or the ETL's SQL; its usage from the query log; each table's and column's meaning, drafted then confirmed | the catalog first, then lineage and usage, then the meanings: the data-meaning skill drafts, a named person confirms | the data pack's `introspect` (the registry's `data@cynergis`, installed first: ADR-0010), the data pack's `lineage`, the data pack's `usage`, the data pack's `meaning`, the data-meaning skill, the data pack's `confirm` |
| Who may do what with the data | access policy as facts on the data layer: a rule permits or forbids a permission for a role or a team, a table or a column says how it is classified and whether it holds personal data; the active rules compiled into a Cedar bundle with a JSON form, hashed and signed, carried by the deploy pipeline | the rules as facts first, drafted then activated by a named person; only active rules compile; the graph is edited, never the bundle | `oto init --ontology policy` (the registry's `policy@cynergis`, installed first: ADR-0010), `oto decide policyrule.<id> status=active --by <who> --at <date>`, the policy pack's `compile`, the policy pack's `verify`, the policy pack's `list`, the policy pack's `snapshot --agent <id> --principal <id> [--ttl <hours>]`, the policy pack's `denials --events <file>`, `X-Oto-Principal` on a served read, the policy pack's `iam [--apply --by <who>]` for the generated system's bindings (build/iam, never enforced by OTO), PL1 to PL8 |
| What the architecture says | a framework's model (CALM, through the registry's calm pack: `oto pack add calm`) imported and exported; the code map of a repository; both compiled on every merge by the architecture workflow (oto-architecture.yml) | import the model first, then map the code, then let the workflow compile both; what the model does not say (where a service runs, what composes it) is the estate's to declare, never invented | `oto arch import --framework calm --file <model> --at <date>`, `oto arch export --framework calm`, `oto arch map --repo <path> --repository repo.<id> --at <date>`, `oto arch compile --at <date> --by <who>`, `oto arch impact --decision <id>` |
| What the domain says | an event-storming board read in; the capture form, by interview; each element's readiness, signed off by a named person | the board first when a session happened, the interview otherwise; readiness is the analyst's to say, never the board's | the `ddd` pack's storm command, which reads the board into a capture (the pack is the registry's, `ddd@cynergis`, installed first: ADR-0010), `oto curate propose --from <capture>`, the capture-form skill, `oto decide <node> readiness=ready --by <name> --at <date>`, `oto arch measure --nfr <id>`, the work pack's `event verdict` for what a factory reports; building from the graph is the oto-factory plugin's, from its own repository (Cynergis/oto-factory) |
| Which sandboxes are there | all of them, running or stopped, with their last use and folders; the ones no longer used removed, the folders kept; Desktop's stale SSH connections named | remove what is stopped and idle or whose folders are gone, after a checklist and a yes; never the one in use | the sandboxes skill (`/oto:sandboxes`): `oto sandbox ls`, `oto sandbox stop <name>`, `oto sandbox rm <name>` |
| Which packs are on | the engine alone (a sandbox starts that way); the packs and plugins the registry offers, chosen from a checklist or on advice from what the project is | the packs the project's work needs, turned on for the project so the choice travels with it | the packs skill (`/oto:packs`): `oto pack list`, `claude plugin install <pack>@cynergis --scope project`, `oto lock --use`, then `/reload-plugins` |
| Where Claude works | on this computer; in a Docker sandbox made from OTO's kit, driven from Claude Desktop's Code tab or a terminal | the sandbox for a tester or a newcomer, or when the work runs commands on a cloud project | the sandbox skill (`/oto:sandbox`): `oto sandbox status`, `oto sandbox up` |
| Beyond this machine | do not; or bind wider with a token; in an OTO sandbox, the published port (no token: it reaches only the computer) | localhost, unless a team needs it; in a sandbox, `oto serve --http 8798` and http://localhost:8798/ on the computer | `OTO_SERVE_TOKEN` in the environment, `oto serve --http 0.0.0.0:<port>`, `--cors <origin>`; `oto sandbox status` lists the published ports |
| Readers without the documents | a query repository they sync; a static site | the query repository | `oto publish --repo <url>`, `oto sync --repo <url>` |
| Environments with approvals | one store for everyone; dev, test and prod, the same build promoted with an approver on record | one store until someone must approve what readers see | `oto deploy init`, `oto deploy check`, `oto publish --to dev`, `oto publish --to test --promote <commit> --by <who>`, `oto deploy status` |
| Measuring answers | none; a gold set per document | a gold set, a few questions per document | `oto bench start`, `oto bench add --from <questions>`, `oto bench run`, `oto feedback` |

## 4. Why

OTO writes its reasons down. When someone asks why, read the reason where it is recorded and tell it
in plain words; if nothing is recorded, say that, because an unexplained rule or class is a finding in
itself.

| The question | Where the reason lives | Read it with |
|---|---|---|
| Why does this class or relation exist? | `ontology.rationale.json`, one entry per class with who confirmed it | `oto ontology rationale --project <root>`, and the ontology's `README.md` |
| Why did the graph derive this fact? | the rule's `why`, and the premises recorded with the fact | `oto rules explain <rule-id> --project <root>`; for one fact, the `kg_explain` tool or `oto query explain "<entity>"` |
| Why was this proposal refused? | the check report | `oto curate check --project <root>`, `oto query pending --project <root>` |
| Why did this fact change, and when? | the ledger: every apply with `--by` and `--note` | `oto query overview --project <root>` (the ledger tail), `oto curate log --project <root>` |
| Why is this fact superseded? | the supersession pointers and dates on the node | `oto query entity "<term>" --history --project <root>` |
| Why was this decided? | `Decision` facts, the spec skill's convention | `oto query by-type Decision --project <root>`, then `entity` for one |
| Why is OTO built this way? | the architecture notes | `docs/ARCHITECTURE.md` in the engine repository |
| What is this domain's graph for? | the project's `GUIDE.md`, installed from the ontology when it carries one | quote its sections; `oto ontology show <name>` says whether the ontology has a guide |

## 5. Hand-off

The concierge ends its turn by saying, in plain words, who takes it from here ("The product's guide
can take you from here; shall I hand you over?") and, when the person agrees, starts that skill itself. Its
command is a detail, said only when asked. The concierge does not do the skill's work.

The project's packs come first. `oto status` lists them under `packs`, and `oto status --json`
gives each skill's command (`/<pack>:<skill>`) and what it does: when the person's need is what a
pack's skill does (model a part with DDD, design a pipeline, define a report, build a template),
name that skill; it is the domain's own way, and the table below is what OTO offers every project.
Never name a skill of a plugin the project does not list, nor one marked `NOT INSTALLED`.

A playbook (a pack marked `(playbook: <skill>)`; `oto pack list --playbooks` before there is a
project) leads a whole journey, a product from an idea to its readers, say. When the person wants
that journey, hand over to the playbook and stop: it runs the scenes, and it comes back to you for
"where are we". You orient; it leads.

| When the person wants to | Load | They tend to say |
|---|---|---|
| Go from a folder of documents to a served graph | build-knowledge-base | "build a knowledge base from these", "turn this folder into a graph" |
| Design or restructure the vocabulary | ontology-interview | "what classes should we have", "the vocabulary is wrong" |
| Add one document, or one correction someone said | curate | "add this document", "that fact is wrong", "X changed" |
| Write what someone said into the inbox as a source | capture | "remember that", "note this down", "they told me" |
| Use what they highlighted or copied, without pasting it | selected-text | "the selected text", "what I copied", "my clipboard" |
| Keep the plan: block, unblock, tell someone, see the board, answer what waits | work | "X is blocked on Y", "what's blocked", "tell Y", "what's waiting for me", "PR 60 merged X" |
| Answer the vocabulary's questions in an interview, each confirmed group into the graph | capture-form | "capture against the pack", "fill the form", "interview me for this" |
| Find facts citing a document nobody can open | vet-provenance | "the documents moved", "is the graph still grounded" |
| Ask a question of the graph | query-knowledge | any question about the domain |
| Do what one of the project's packs does | that pack's skill, from `oto status --json` (`packs`) | "model the domain", "design the pipeline", "define a new report", "build the template" |
| Measure answer quality | evaluate | "how good are the answers", "make a gold set" |
| Write a spec or an ADR from the graph | spec | "write the spec", "draft an ADR", "design brief" |
| Do something about an entity: list, confirm, invoke, record | act | "create the repository", "check that it exists", "call the API and record it" |

## 6. Questions about the graph itself

Route to query-knowledge. Two exceptions the concierge handles itself:

- A question about a fact that is on its way in: `oto query pending --project <root>` lists what
  sits in a proposal or the candidate, by station, with the verdict and the reason for a refusal.
  Say which station it is at and never present it as believed.
- "What is this project?": `oto status`, then the project's `README.md` and `GUIDE.md` when it
  has one, then the counts from `oto query overview`, told in a few plain sentences.
- "What can be done about X?": `oto query tools --on <entity>` (the `kg_tools` tool) lists the
  tools the graph declares on it, ready or not and why, with the inputs bound and the declared
  way to invoke. OTO never invokes; the caller does, then `oto tools record <id> --on <entity>
  --by <who> --response <file>` turns the response into a run record, a source document and a
  proposal that goes through the gates. Say which.
