---
name: query-knowledge
description: >-
  Answer a question from an OTO knowledge graph with temporal correctness: resolve the terms,
  read current facts only, cite the source and the date, frame what it means, and say plainly
  what the graph does not know. History and as-of dates only when asked. Read-only. Use whenever
  someone asks a question about the domain an OTO project covers, or wants an insight from it.
---

# Answer from the graph, dated and cited

The graph does the retrieval. Your job is to ask it the right thing, refuse to bluff, and frame
the answer. This skill changes nothing; a correction goes to the **curate** skill.

## The tools

Prefer the `kg_*` tools if the project's server is registered with your host (the OTO plugin
registers `oto serve` as an MCP server). Otherwise the same functions run one per call:

```bash
oto query --project <root> resolve "<term>"                 # jargon or alias -> entity ids; says if NOT ingested
oto query --project <root> entity "<term>" [--history] [--as-of YYYY-MM-DD]
oto query --project <root> neighbors "<term>" [<relation>]
oto query --project <root> search "<words>" [n]              # full-text over corpus, notes and cards
oto query --project <root> by-type <Class> [state] [limit]
oto query --project <root> count --type <Class> [--attr k --value v]
oto query --project <root> group <by> [--type <Class>]
oto query --project <root> docs [filter]                     # what is ingested, and how recent
oto query --project <root> stale                             # every superseded fact and its successor
oto query --project <root> overview [limit]                  # the map of the whole graph, for a global question
oto query --project <root> explain "<term>" [rel]             # why a derived fact holds: rule, premises, evidence
oto query --project <root> define "<term>"                   # what a class, relation or attribute means, and why it exists
oto query --project <root> policy                            # standing policy findings
oto query --project <root> pending                           # what is on its way in, by station: not believed yet
```

A fact `pending` lists is not believed: it sits in a proposal or the candidate and has not passed
the gates. Say so if the question is about it ("a proposal from the memo would add this; it is in
review"), and never present it as current. A fact marked `[derived by <rule>]` is an inference the rules made from asserted facts, not
something a document states. Say so when you use one, and run `explain` if the question turns on
it: the chain ends in documents, and that is what you cite.

## Method

1. **Resolve first.** Run `resolve` on the words the question uses. People use their own terms; the
   lexicon maps them. If a term resolves to nothing, say so and ask which entity is meant. Do not
   guess a near match. If `resolve` says a document is not ingested, that is the answer: the graph
   cannot know what it has not read.
2. **Read current facts.** `entity` and `neighbors` return `status: current` by default and steer a
   superseded id to its successor. For a multi-hop question, follow the relations they print; the
   ontology (`build/ontology/ontology.md`, or `define <term>`) says what each relation means. Use `search` for a
   thematic question, then `entity` on what it surfaces.
3. **Check the date before answering.** Every fact carries `as_of` and `valid_from`; state them when
   precision matters ("current as of 2026-03-01"). A superseded fact is history: mention it only if
   the question is about history.
4. **Answer, then cite.** The entity ids and the `sources` or `source_doc` of every fact you used.
   An uncited number is not an answer here.
5. **Frame it.** After the direct answer:
   - *So what:* what it implies, if anything.
   - *Open:* what the graph does not say. Name the missing fact, the undated fact, or the document
     that is not ingested. Never fill the gap from general knowledge.

## Global questions: a synthesis, labelled as one

Some questions start from no entity: "what is going on here", "what are the main themes", "what
changed this quarter", "what does this organisation seem most concerned with". The graph holds no
fact that answers them. What it holds is the material for a reading, and a reading is only
trustworthy if it says what it rests on.

1. **Start from the map.** `kg_overview` (or `oto query overview`): counts by class, relation and
   status, the most connected entities, top tags, what the corpus covers and how recent it is, the
   superseded facts, and the recent ledger of changes with their reasons.
2. **Read what the map points at.** The entity cards of the most connected nodes (`kg_entity`),
   the authored notes under `notes/` (they are in `kg_search`), and for "what changed" the ledger
   entries and `kg_stale`. Follow relations where the question needs it. Do not read the whole
   graph; read what the map makes relevant, and say that is what you did.
3. **Write the synthesis in this shape, and no other:**

   > *A reading of the graph as of <the overview's most recent fact date>, drawn from <N> entities
   > and <M> notes. It is a synthesis, not a fact; every theme below names the facts it rests on.*
   >
   > **Theme.** One or two sentences. *Rests on:* entity ids and the documents they cite.
   > (repeat)
   >
   > **Not covered:** what the corpus does not reach, and what the question assumed that the
   > graph does not hold.

   A theme with no facts under it is not a theme; drop it. A theme that rests on one node is an
   observation about that node; say so.
4. **Decline what a synthesis cannot ground.** "Why is morale low" has no facts in a graph of
   procedures. Say what the graph could speak to instead.

### Theme notes: keep the readings that recur

A global answer worth giving twice is worth keeping. Write it to `notes/themes/<slug>.md` in the
project, and it becomes part of the corpus: indexed by the next build, found by `kg_search`,
dated so its staleness is visible. Front matter records what it rests on:

```markdown
---
theme: maintenance-cadence
as_of: 2026-09-13
rests_on: [machine.press-01, procedure.pm-2, procedure.pm]
documents: [handbook, memo]
---
# Maintenance cadence

A reading of the graph as of 2026-09-13 ...
```

A theme note is **authored**, never generated: it is a person's or an agent's reading, and it is
refreshed by hand when `kg_overview`'s ledger shows the facts it rests on changed, or retired
when they no longer hold. A note whose `as_of` is older than a change to one of its `rests_on`
facts is stale; say so when you cite it, and offer to refresh it. Never present a theme note as
a fact: it cites facts.

## History and points in time, only when asked

- "What did we believe before?" → `entity "<term>" --history`
- "As of <date>?" → `entity "<term>" --as-of <date>`
- "What changed recently?" → `stale`

## Guardrails

- **Current by default.** Never present a superseded or proposed fact as current.
- **Always date and cite.** If a fact has no date, say it is undated.
- **Stated, not inferred.** If two entities are not connected in the graph, say the link is unstated.
- **Do not answer from outside the graph.** If it is not there, say so; a confident answer from
  general knowledge is exactly the failure a cited graph exists to prevent.
- **Read-only.** A wrong answer that the user corrects is an `oto feedback record`, and a fact to
  change goes through the **capture** skill (a dated note into the inbox, then the pipeline) or,
  for a curator working locally, the curate skill. The one thing this skill may write is a theme
  note under `notes/themes/`, and only when the user asks to keep a reading.
- **A synthesis is labelled as one**, dated, and names the facts it rests on. A global answer
  without that label is exactly the kind of confident, unverifiable text a cited graph exists to
  prevent.
