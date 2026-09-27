---
name: curate
description: >-
  Turn a document, or a statement someone made, into curated graph facts with provenance and dates.
  Four gates: recap what the source says, check contradictions against what is already believed,
  preview the exact diff, apply only on confirmation. Contradictions resolve by supersession, never
  by overwriting. Use whenever new knowledge must enter an OTO project.
---

# Add knowledge to the graph

This is the only step that changes what the knowledge base believes, so it is the only one that must
never happen by accident. Nothing you do here touches the live graph until a person says yes.

    oto curate start     copy the live graph to a candidate
    (you edit the candidate)
    oto curate check     what it changes, and what is wrong with it
    oto curate apply     promote it
    oto curate undo      put it back

## The rule that matters most

**When a fact changes, keep the old one and mark it superseded. Never overwrite.**

Overwriting destroys the answer to "what did we believe on the 14th", which is the property this whole
system exists to protect. `oto curate check` reports every changed value that has no supersession
record. Treat that report as an error unless the change is a correction of a typo.

---

## Phase 1 — Read and recap *(Gate 1)*

1. If the source is a file, drop it in `inbox/` and run `oto ingest --project <project>`. The run
   claims it into `processing/` and writes `build/documents/<slug>.md`; a failure lands in
   `errors/<run>/` with the reason beside it. For a deck or a PDF, run `oto figures` too: a figure
   with no description is invisible to retrieval, and the facts on it will be missing from your
   recap. If the run announces a **new version** of a document the graph already cites, every
   fact citing the old version is now **pending re-attestation**: `oto curate check` lists each
   one until the new proposal lists it again (which re-attests it) or retires it, and
   `oto ingest complete` refuses to close the run while any is outstanding.
2. Read the extracted Markdown in full. A summary of a summary loses exactly the specifics that
   make a fact checkable.
3. Recap to the user, before proposing any edit:
   - what the source is, and its date
   - the facts it asserts that are new
   - the facts it asserts that **differ** from what the graph already says
   - what it does not say, that you might be tempted to infer

**Stop and confirm the recap.** If the recap is wrong, every edit after it is wrong.

## Phase 2 — Check what is already believed *(Gate 2)*

For each fact in the recap, query the graph before writing anything:

```bash
oto query --project <project> resolve "<the term>"       # the built graph, via the lexicon
oto query --project <project> entity "<the entity>"
oto curate resolve --project <project> --term "<the term>" # the candidate too, once one is open
```

Use the second form inside a batch: an id another document's proposal created is in the candidate
and not yet in the database, and inventing a second id for it is how a graph rots.

Three outcomes, and they lead to different edits:

- **Not there.** A new node.
- **There and agrees.** Add the new source to `sources`, and nothing else. Do not duplicate the node.
- **There and disagrees.** A supersession. This is the case to slow down on.

Report the contradictions to the user **before** editing. Say what the graph believes, what the source
says, and which is newer. Do not decide silently which one wins.

## Phase 3 — Write the candidate

```bash
oto curate start --project <project>
```

Edit `graph.candidate.json`. Never the live graph.

**Every new node carries:**

| Field | Why |
|---|---|
| `id` | stable, lowercase, dotted, derived from the label |
| `type` | must be declared in the vocabulary, or the build fails |
| `label`, `aliases` | how people actually refer to it, so a query resolves |
| `summary` | what it is, in the source's words |
| `attributes` | values about it. Where the class declares an attribute, the value must fit the declared type (`oto ontology check` shows them); an undeclared key on a declaring class is reported |
| `as_of` | when you recorded it |
| `valid_from` | when it became true in the world, which is often earlier |
| `source_doc`, `sources` | a fact that cites nothing cannot be checked |
| `evidence` | where in the document: `[{"doc": "<slug>", "where": "p.12" or "§3.2" or "slide 4", "quote": "<the sentence>"}]`. This is what lets a reader verify the answer without re-reading the document; `check` reports a new fact without one |
| `source_type` | omit for a document. `human_assertion` for a recorded statement. `inference` if you keep something the source implies but does not state, and say so in the recap |

**For a supersession, three edits, not one:**

1. On the old node: `status: "superseded"`, `valid_to` (the date the new fact took effect),
   `superseded_by` pointing at the new id.
2. A new node with a new id, `supersedes` pointing back, its own dates and sources, and a
   `change_note` saying **why** it changed.
3. Re-point the edges that should follow the new fact. The old node keeps its own edges, which is what
   makes the history readable.

**Only assert what the source says.** If you are inferring, say so in the recap and let the user decide.
A confident wrong fact is worse than a missing one, because nothing will ever flag it.

## Phase 4 — Check *(Gate 3)*

```bash
oto curate check --project <project>
```

Read all four sections:

- **blocking** — undeclared types or relations, edges pointing nowhere, bad dates, duplicate ids,
  and a supersession chain that does not point both ways or retires nothing. Fix every one.
- **contradiction** — a value changed with no supersession record. Fix it, or explain why it is a
  correction rather than a change.
- **gap** — a node with no date, no source, no citation or no evidence locator; a date handoff
  that does not match; an edge whose endpoints do not fit the declared domain or range; a fact
  pending re-attestation; a `warn` policy rule the candidate would violate (a `blocking` one is
  blocking). Fix these too. They are not blocking because a build must not fail on
  them, but a fact with no source is not knowledge and a fact nobody can locate is not checkable.
- **privacy** — personal data in the text you are about to add. Read the note below.

## Phase 5 — Apply *(Gate 4)*

**Show the diff and ask.** Then:

```bash
oto curate apply --project <project> --by "<you>" --note "<what this made answerable; what it left open>"
oto build --project <project>
oto ingest complete --project <project>    # if the source came through the inbox
```

Every apply appends an entry to `changelog.jsonl`: the counts, each fact retired with its change
note, the new sources, who applied it, and your `--note`. `oto curate log` reads it. Write the
note as the report below, condensed to two or three sentences; a year on, it is the only record of
why the graph changed.

Then report, in this order:

1. **What changed:** nodes and edges, and each fact superseded with its reason.
2. **Now answerable:** the questions this document lets the graph answer that it could not before.
3. **So what:** anything the new facts imply that someone should decide or do, if anything. State
   it as an implication of the facts, not as advice from you.
4. **Still open:** what the document raised and did not settle, and what it does not say that a
   reader might assume it does.

If an apply turns out to be wrong, `oto curate undo` restores the previous graph.

`oto ingest complete` moves the source file from `processing/` to `archive/` and closes the run.
It refuses while a candidate is open or the build predates the document, so a file in `archive/`
always means the graph holds it. Run it last.

---

## Correcting from something a person said

The same four gates, a shorter path. Someone says "that is wrong, the deductible went up in April".
That correction is often the most valuable knowledge in the room, and it is the easiest to lose.

If you are **not** already in a curate session, or the project lives in a repository, use the
**capture** skill instead: it writes the statement into the inbox as a dated source document and
the pipeline takes it from there. What follows is the curator's local path.

**Do not write it into the graph as an unsourced fact.** An unsourced fact looks exactly like a sourced
one, and nobody can check it later.

### 1. Record the statement first

```bash
oto curate assert --project <project>   --text "<what they said, in their words>"   --by "<who said it, and their role>"   --at <the date it refers to>
```

Three things matter here:

- **Their words, not your summary.** The log exists to answer "why does the graph say this" months
  later, and a paraphrase loses the specifics.
- **`--by` is required.** An unattributed claim cannot be followed up, and a correction you cannot
  follow up is a rumour.
- **`--at` is never defaulted.** A correction usually refers to when something became *true*, not when
  it was typed. Ask. If they do not know, ask what they do know and record that.

The log is append-only. It records the claim; nothing has entered the graph yet.

### 2. Resolve what it is about

```bash
oto query --project <project> resolve "<the term they used>"
```

People use their own words. If the term resolves to nothing, ask which entity they mean rather than
guessing. Creating a near-duplicate node is the most common way a graph quietly rots.

### 3. Author the change, citing the assertion

Every fact derived from the statement carries:

```json
"source_type": "human_assertion",
"sources": ["assertion:a-0007"]
```

A fact citing an assertion that is not in the log is a **blocking** error. That check is what makes the
citation mean something.

If it contradicts what the graph believes, and it usually does, that is a supersession: the three edits
above. Put their reason in `change_note`, in their words.

### 4. Check and apply

As before. `oto curate assertions` then shows how the graph's knowledge is sourced:

```
document         412
human_assertion   17
inference          0
```

That count is worth watching. A graph drifting toward assertions is one where the documents have
stopped keeping up, and that is a signal about the corpus rather than about the people.

---

## Personal data

The privacy scan runs on the text this change **introduces**. It blocks credentials, social insurance
numbers and payment cards, and warns on email, phone, vehicle identification numbers and postal codes.

**It is a safety net, not a review.** It cannot recognize a name, an address or a medical detail
written as prose. That judgement is yours:

- Does answering the question need this personal detail, or only the role?
- Would a summary work where a quotation would not?
- A description you write is new text entering a searchable index. It can reintroduce something that
  was deliberately removed, and nobody will notice.

When in doubt, record the role and cite the source. A reader who needs the name can open the document.

## Guardrails

- **Never edit the live graph.** Edits go in the candidate, always.
- **Never overwrite a contradicted fact.** Supersede it.
- **Never invent a date.** If the source does not say when something became true, use the source's own
  date and say so.
- **Never assert what the source does not say.** Mark inference as inference in the recap.
- **Do not apply with blocking problems.** `--force` exists for a maintainer fixing a broken graph, not
  for getting past a gate.
- **Stop at every gate.** Four confirmations feel like a lot until the first time one of them catches
  something.
