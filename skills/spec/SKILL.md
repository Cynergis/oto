---
name: spec
description: >-
  Draft a product specification, an architecture decision record, or a design brief from what an
  OTO knowledge graph holds: the current facts as the ground, every claim cited to an entity and
  its source, open questions where the graph is silent, and the resulting decisions recorded back
  into the graph as first-class facts. Use whenever someone asks for a spec, an ADR, a design or
  the reasoning behind a choice, in a domain an OTO project covers.
---

# Write a spec from the graph, and write the decision back

A specification written from memory says what its author believes. One written from the graph
says what the organisation has recorded, cites where, and marks where the record stops. That is
the whole difference, and it is why this skill exists: the document you produce is only worth
the citations in it.

Two halves. First the graph feeds the document: constraints, existing components, decisions
already taken, risks, requirements, owners. Then the document feeds the graph: the decisions it
makes become `DecisionRecord` facts through the pipeline, so the next spec starts from them
instead of rediscovering them.

## Phase 1 — Scope, then resolve

1. State in one paragraph what is being specified and for whom. Get that confirmed before reading
   anything; a spec for the wrong scope is polished waste.
2. Resolve every noun in the scope statement:

   ```bash
   oto query --project <root> resolve "<term>"       # jargon -> entity ids; says if NOT ingested
   oto query --project <root> docs                    # what the corpus holds, and how recent
   ```

   Anything that resolves to nothing is either not in the graph, or named differently. Ask. Do
   not invent an entity to write about.

## Phase 2 — Ground the document

Read before writing, and read the graph rather than the documents, because the graph is the
curated record and the documents are its evidence:

```bash
oto query --project <root> overview                  # the map: classes, hubs, recent changes
oto query --project <root> entity "<term>"           # each entity in scope; its relations, sources, evidence
oto query --project <root> neighbors "<term>" [rel]  # what it depends on, who owns it, what threatens it
oto query --project <root> by-type DecisionRecord     # decisions already taken; never re-decide silently
oto query --project <root> by-type Requirement
oto query --project <root> by-type Risk
oto query --project <root> policy                    # standing findings: what the rules say is wrong now
oto query --project <root> explain "<term>"          # why a derived fact holds, down to its documents
oto query --project <root> search "<words>"          # passages, notes and theme notes for a topic
```

For each fact you will rely on, keep three things: the entity id, its `as_of` or `valid_from`, and
its source. A fact marked `[derived by <rule>]` is an inference; cite the chain `explain` gives
and say it is derived. A fact whose `resolve` says "not ingested" cannot ground anything.

Ask the graph what the document must not contradict:

- **Decisions already recorded.** Every `DecisionRecord` touching an entity in scope. A new
  decision that reverses one is a supersession, not an edit; say so in the spec.
- **Requirements** attached to the systems or capabilities in scope, and their status.
- **Risks** that reach the system (`explain` shows the rule that carried them there).
- **Owners.** `Team` nodes and `owned_by` or `decided_by` relations: who has to agree.
- **History**, when the choice has been made before: `entity "<term>" --history` and `stale`.

## Phase 3 — Write it

Use the shape below unless the user has a house ontology; the sections exist because each one
answers a question a reviewer will ask. Keep the citations inline, as `(entity.id; source)`, so a
reader can check any sentence with one `oto query entity`.

```markdown
# <Title>: <product spec | architecture decision | design brief>

*Drawn from the <name> knowledge graph as of <overview's most recent fact date>. Every claim
below cites the entity it rests on; an uncited sentence is the author's proposal, not a fact.*

## Context
What exists today and why it matters, from the graph. (system.payments; arch-overview §2)

## Problem
The gap or the decision to make. Cite the requirement or risk that raises it.

## Constraints
Recorded decisions, requirements, policies and risks the answer must respect. Each cited.
A `[derived]` constraint says which rule derived it.

## Options
Two or more, honestly. For each: what it changes in the graph's terms (which components,
interfaces, data stores), what it costs, what it risks. Cite the entities it touches.

## Decision   (an ADR) | ## Proposal   (a spec)
The choice, in one paragraph. Then the consequences, as future facts: what will be true of
which entities once it is done.

## What the graph does not say
Every question this document needed answered and the graph could not: the missing entity,
the undated fact, the document not ingested, the owner not recorded. This section is
mandatory and never empty; a spec that claims the graph covered everything is not credible.

## Decisions to record
The `DecisionRecord` facts this document creates (see the convention), ready for capture.
```

Rules for the prose:

- **A claim without a citation is a proposal.** Write it as one: "we propose", not "the system
  requires". The reader must be able to tell the recorded from the suggested at a glance.
- **Never fill a gap from general knowledge.** If the graph does not say which database the
  ledger runs on, the spec says that is unknown and lists it under "What the graph does not say".
  A confident guess is the failure a cited graph exists to prevent.
- **Superseded is history.** Cite current facts. If a superseded fact explains why something is
  the way it is, cite it as history with its `valid_to`.
- **Say which model wrote what.** If a model drafted the options, the document says so at the
  top. The graph's facts are the organisation's; the reasoning between them is yours or the
  model's, and a reader has the right to know which.

## Phase 4 — Record the decisions back

A decision that lives only in a document is one the graph will contradict within a quarter. The
convention in [references/decisions.md](references/decisions.md) says how a decision becomes a
`DecisionRecord` fact with `decided_by` relations, dated, sourced to the spec itself.

1. Save the finished document where the project keeps sources (`inbox/`), or capture the
   decision statements with the **capture** skill if the decision was made in conversation.
2. The pipeline takes it from there: ingest, a proposal with the `DecisionRecord` nodes and their
   relations, the curate gates, a pull request in repository mode. The spec is then the
   `documented_in` source of its own decisions, and the `decision-is-documented` rule stops
   flagging them.
3. If the decision reverses a recorded one, the proposal supersedes the old record and the
   `change_note` says why, in the spec's words.

Report, in this order: what the document decided or proposed; which recorded facts it rests on;
what it could not ground; and which `DecisionRecord` facts are now pending capture.

## Guardrails

- **Read-only until Phase 4**, and Phase 4 writes to the inbox or a candidate, never to the graph.
- **Cite the entity, not the document alone.** The entity is the curated fact; the document is its
  evidence. Both, when precision matters.
- **Do not re-decide silently.** A recorded decision is a constraint until a new record supersedes
  it, and that supersession is a visible section of the spec.
- **"What the graph does not say" is never empty.** If you cannot find anything for it, you have
  not looked hard enough at the scope.
- **Never write to `graph.json`.** Decisions enter through capture, ingest and curate, like every
  other fact.
