---
id: ADR-0012
title: An ontology is made in a workspace of its own; a knowledge project uses one and does not define it
status: accepted
decided_on: 2026-11-01
decided_by: Chiheb Dkhil
governs: [workitem.epic-i, workitem.epic-j]
---

# An ontology is made in a workspace of its own; a knowledge project uses one and does not define it

## Context

An ontology is made once and used many times: several teams build knowledge graphs on the same
vocabulary, and the vocabulary moves on by releases they take or leave. Until this decision both
happened in one place. A knowledge project held the vocabulary files beside its graph, the
ontology-interview skill wrote them there, the build-knowledge-base skill had a phase for changing
them in the middle of ingesting, `oto ontology export` copied them out as an ontology whose sample was
that project's own graph with its confirmations emptied, and every other team started from the copy.
The ontology had no home of its own: it was born inside somebody's knowledge project, edited beside
live data, and released as a side effect.

The engine already modelled the other end. A pack is the unit the registry carries (ADR-0008,
ADR-0010, ADR-0011), a project records the pack and release it started from, `oto status` says when
a newer release exists, `oto ontology diff` says what it would change and how many of the project's
nodes it touches, and `oto ontology update` moves the project. What was missing was a place where
the pack is made, and a rule that the consuming project does not edit what it consumes.

Testing a graph deployed from the engine against a shared store made the cost concrete: the team
that owns the words and the teams that assert facts in them are different teams, with different
gates and different rhythms, and one project cannot serve both.

## Decision

There are two kinds of project. An ontology is made in an **ontology workspace**, a pack in the making in a directory of its own with a trial project beside the deliverable, released to the registry through the pack's gates; a **knowledge project** starts from packs, derives its vocabulary from them and does not edit it, and a term it lacks is a release of the pack or a pack that extends it.

## Consequences

**The record.** `project.config.json` carries `kind` (`knowledge`, or `concierge` for a root that only
routes) and `vocabulary` (`derived` or `own`). A project started from a pack, or from an ontology an
installed pack carries, is `derived`: its `ontology.config.json` is what the packs compose, written by
the engine with a header saying so. A project started with no ontology or from a directory, and every
project made before this decision, is `own`, and nothing changes for it; a derived project takes its
vocabulary back by saying so.

**What derived means.** `oto ontology check` and `accept` refuse a hand edit and name each difference
and where a change belongs; `oto ontology import` into a derived project is refused; `oto ontology
update` writes the file again from the packs' current releases; `oto status` says `derived from
<pack> @<release>` (`oto/model/derived.py`).

**The workspace.** `oto pack new <name> --to <dir>` lays it out: the pack with a starter vocabulary to
fill, on `oto-core` or on the bases `--extends` names, which it embeds; a `trial/` knowledge project;
and two workflows, the pack's gates on every pull request and a release on a tag. `--from-project
<dir>` opens a workspace from a project that grew its own vocabulary, keeping its confirmations.
`oto pack check <dir> --strict` holds the deliverable to the vocabulary's three gates and the
rationale, a reason and a named confirmation for every term the pack itself declares; without the
flag the rationale stays advisory, for the packs the registry held before. `oto pack try <dir>` writes
the trial's vocabulary from the pack, seeds it from the pack's sample while it holds no fact of the
pack's own, builds it and asks its questions; the trial's documents and graph are its own.
`oto pack publish` ships the pack and leaves `trial/` and `.github/` behind.

**The skills.** The ontology-interview skill works in a workspace and ends with the pack's gates and
its release. The build-knowledge-base skill starts a project on a pack and sends a missing term to the
workspace, never into the project's file. The concierge and the start skill route by what is being
made.

**The sandbox.** `oto sandbox up --kind knowledge|ontology` lays the project out before the sandbox
is made; `--repo <owner/name>` backs it with a repository created and pushed with the token the
person names, stored as the sandbox tool's own GitHub secret so the agent inside pushes and the token
never enters the sandbox; `--no-repo` keeps it local. The sandbox skill proposes the name, the folder,
the kind and the repository from one answer.

**What stays.** The four curate gates, the build, the stores and the deploy; the pack layout and the
registry; the lock; the composition rules; the engine's one vocabulary, `oto-core`, and the rule that
it defines no other (ADR-0011). An ontology discovered from documents still reads them: the workspace
ingests into its trial project, so the deliverable changes and the practice does not.

**Open.** Whether `trial/inbox` is ignored by git by default, since a client's documents may be read
there; how `update` of one pack treats a base another pack pinned; which GitHub owner the sandbox
proposes a repository under. Decided as they come up, under this decision.
