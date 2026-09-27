---
name: capture
description: >-
  Turn knowledge that arrived in conversation into a dated, attributed source document in an OTO
  project's inbox, so it enters the graph through the same ingest, drafting, gates and pull
  request as any file. Use when someone corrects a fact, states a decision, or tells you something
  the graph should hold ("actually the owner changed in March", "remember that", "record this"),
  and especially when the project lives in a repository or the person is not a curator.
---

# Capture what was said

A correction spoken in conversation is often the most valuable knowledge in the room and the
easiest to lose. Do not write it into the graph. Write it down as a source, in the speaker's words,
and let it enter the way a document does. The graph will cite it; the speaker is who to ask.

Two paths exist for spoken knowledge. `oto curate assert` records a statement in the assertions
log for a curator who is editing the graph locally right now. **This skill is the other path**: a
document in the inbox, for everyone else and for a project that lives in a repository. Prefer it
unless you are already inside a curate session.

## 1. Recap, in their words *(gate)*

Before writing anything, say back what you are about to record:

- each statement, quoted, as they said it;
- who said it, and their role;
- the date it **refers to**, which is usually when something became true, not today. If they do
  not know, ask what they do know, and record that;
- what it is about: run `kg_resolve` (or `oto query resolve`) on the terms they used, so the note
  names entity ids where the graph has them, and say when it does not.

**Ask them to confirm the recap.** A paraphrase loses the specifics that make a fact checkable,
and the note will be cited for years.

## 2. Write the note

```bash
oto capture --project <root> --title "<what it is about>" \
  --by "<name, role>" --at <YYYY-MM-DD> \
  --statement "<first statement, verbatim>" --statement "<second>" \
  --about <id>,<id> --context "<what prompted it, one line>"
```

This writes `inbox/<date>-<title>.md` with a fixed header: captured on, by, recorded by, about;
the statements numbered and attributed; the context. It refuses a missing author or a non-date,
and warns about an id the graph does not hold.

## 3. Send it into the pipeline

- **The project is a repository:** commit the note to `main` and push. A push to `inbox/` runs the
  ingest, the author workflow drafts the facts, and a pull request opens for the curator. Say
  which pull request to watch. Ask before pushing; it is the step that leaves the machine.
- **The project is local:** `oto ingest --project <root>`, then the **curate** skill for this one
  document, or **build-knowledge-base** if a batch is waiting.

## 4. Tell them what happens next

The statements are now a document. Nothing is in the graph yet. When the pull request is merged
or the curate apply is confirmed, the facts will cite `<date>-<title>`, and an answer that rests
on them will name the speaker. If the statement contradicts what the graph believes, the drafter
will write a supersession and the curator will see both sides in the diff.

## Guardrails

- **Their words, not your summary.** Quote. Trim filler; never change meaning.
- **Never default the date.** `--at` is the date the fact refers to; ask.
- **Never write to `graph.json`** from here, and never run `oto curate apply`.
- **One conversation, one note.** Several unrelated corrections are several notes, each about its
  own thing, so each can be superseded on its own later.
- **If they are not sure, record that they are not sure.** "I think it moved in March" goes in as
  said, and the drafter marks the fact as an inference or leaves it out.
