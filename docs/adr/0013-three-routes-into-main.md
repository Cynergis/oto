---
id: ADR-0013
title: A change enters main by one of three routes, decided by what it carries; one gate enforces the route, and a confirmation in a session is the approval
status: accepted
decided_on: 2026-11-02
decided_by: Chiheb Dkhil
governs: [workitem.epic-b, workitem.epic-j]
---

# A change enters main by one of three routes, decided by what it carries; one gate enforces the route, and a confirmation in a session is the approval

## Context

People add to a knowledge graph in three ways. A product owner works in a Claude session on the
board's project and confirms each change there. An architect drops documents in the inbox and
reviews what the pipeline drafted from them. A manager's meeting transcripts arrive on their own
and should land without anyone looking, as long as guardrails hold. Until this decision the engine
gave all three the same pipeline into `main` (ingest, author, checks, deploy, written by
`oto init --repo`) and the same approval: a pull request someone merges. Nothing in the engine or
the repository said who approves what, so a change confirmed by the person who made it waited for
a second person, a change drafted by a machine from documents could merge on a green check, and a
transcript's facts had either everybody's approval or nobody's.

Testing the Northwind Kanban project made the cost concrete: a card captured in a session had no
pull request because the author workflow could not run, `main` was unprotected so a direct push
skipped every gate, and the workflows installed an engine the lock did not record. The design note
*Graph Contribution Journeys* of 2026-11-02 set the three decisions this one rests on: the person
who makes a change in their session approves it there and no other approval is needed; transcripts
are put in the inbox by a process designed later; each project has its own graph, repository and
pipeline.

## Decision

A change enters `main` by one of three routes, decided by what the pull request carries and never by a label someone sets: `session` when the one ledger entry it adds carries a confirmation whose fingerprint equals the fact-level diff between the two `graph.json`, `guardrailed` when the ingest runs it carries came from the transcripts folder the project names, and `reviewed` otherwise; one required check, `oto route`, enforces the route's rule, and a route only moves towards `reviewed`.

## Consequences

**The confirmation.** `oto curate diff --json` is the fact-level diff as canonical JSON, and its
sha256 is the fingerprint: over facts, not bytes, so the same between a candidate and the live graph
on a laptop as between two commits of `graph.json` in CI. `oto curate apply --confirm` writes who
confirmed, when, the fingerprint and what was shown into the ledger entry; the pipeline's apply
carries none. The confirmation is the approval of the `session` route; the gate trusts it only when
the pull request's author is the confirmer and every commit is verified.

**The gate.** `oto route show` says the route from two git refs and why; `oto route check` is the
verdict, fed what only GitHub knows as flags (the authors, whether a review approved, whether the
commits are verified), so the engine never calls GitHub. `oto init --repo` writes `oto-route.yml`,
which gathers the flags and runs the check on every pull request and every review, and
`.github/oto-rules.json`, the branch rules on `main`: pull requests required, the checks `oto checks`
and `oto route` required and up to date, zero approvals at the branch level because the gate asks
per route, the merge queue on. Amended on 2026-11-03: a change to what the gate runs on (`.github/`,
`oto.lock.json`) needs a code owner's approval, which GitHub holds and no workflow can answer for; the
ingest and architecture workflows push to `main` with a deploy key kept in an environment only `main`
deploys from, and that key and an administrator (by a pull request) are the only ones past the rules.
GitHub Actions itself is not: any workflow on any branch can ask for its token. `oto repo rules
--apply` sets them; `oto sandbox up --repo` applies them when it creates the repository.

**The guardrails.** A project declares `routes.guardrailed` in `project.config.json`: the
transcripts folder, the classes a transcript may add, `max_facts`, `additive_only`, `attributed`.
`oto route guardrails` runs five checks on the fact-level diff: additive (nothing the graph believed
is changed, removed or retired), attributed (every added fact is a human assertion citing an entry
of the assertions log that names the speaker, and a transcript of the run), scope (only the classes
allowed; the vocabulary untouched), clean (the run was ingested with `--strict-privacy`; no
transcript's hash appears in an earlier run), bounded. All hold: the change merges with no
approval. One fails: the route moves to `reviewed`, the pull request is labelled and the findings
posted, and a person decides. `oto curate check` holds a transcript's facts to attribution while
the run is open, so the author run cannot draft them otherwise.

**The repository.** A preview per pull request (`oto-preview.yml`: the store at the head on
`preview/pr-<n>` of the query repository, or a workflow artifact; one comment, edited on every
push) is where the `reviewed` route's approval is given. Every workflow installs the engine at the
ref `oto.lock.json` records, and `oto checks` fails when the lock drifts, so the same checks give
the same verdicts and an engine upgrade is a reviewed change. `oto route rebase --onto <ref>`
re-applies a stale pull request's facts onto the new `main` through the gates; the fingerprint is
over facts, so the confirmation holds whenever the facts are the same. It commits nothing: the
session route trusts commits by the confirmer, so the person or their skill runs the git steps it
prints. Amended on 2026-11-04: it also re-chains the audit log, and those steps replace the branch,
because a branch left on the old base still conflicted.

**The skills.** The curate skill, at its fourth gate in a repository, applies with `--confirm` in
the person's identity, commits on a branch, opens the pull request and turns on auto-merge, in the
person's words; it never writes a confirmation the person did not give. The capture skill says a
capture travels the `reviewed` route, since nobody has confirmed the drafted facts, and offers to
draft now instead. The concierge and build-knowledge-base skills name the routes where they say
what happens after a change.

**What stays.** The four curate gates and the candidate as the only way into the graph; the ledger
as the record and the audit chain over it; the build, the stores and the deploy; the two kinds of
project (ADR-0012) and the engine's one vocabulary (ADR-0011). A project that never writes `routes`
and never confirms in a session has every pull request on the `reviewed` route, which is what it
had before.

**Open.** How a person's verified identity and signing key reach a sandbox, so a session change
made there takes the `session` route (today the sandbox pushes with the sandbox tool's secret and
a generic git identity); whether transcripts may be kept in git at all or only redacted extracts;
how transcripts arrive. Decided as they come up, under this decision and the plan
[docs/plans/graph-journeys.md](../plans/graph-journeys.md).
