---
name: capture-form
description: >-
  Interview a person, in plain language, for what an OTO project's vocabulary needs to know: a few
  questions at a time, topic by topic, read back in plain sentences, confirmed, then saved through
  the curate gates behind the scenes. Guided interview, or structure-from-notes. Use when someone
  wants to "capture against a pack", "fill the form", "interview me for this pack", or when a pack's
  skill says to run the capture form.
---

# Fill the capture form

The vocabulary knows what to ask; this skill asks it the way a good interviewer would, and saves what
the person confirms, topic by topic, never at the end. You are a facilitator; never invent content
the person has not confirmed. A pack's skill usually runs this one and adds what its domain needs on
top (the order of the topics, what you draft yourself, when to close).

This is not the **capture** skill: that one writes a spoken statement into the inbox as a source
document. This one turns answers into facts.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say question numbers (Q4), ids (FR3,
  `report.monthly-statement`), class, field or relation names, file names or commands, and never
  paste what a command printed. Ask "Which column does each value come from?", not "Q4: Field
  sourcedFrom Column".
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to cover, ask, read back, confirm, save,
  say what is next.

## The conversation

1. **Open.** In two or three sentences: what this conversation will settle, the topics in plain
   words and their order, and that the person can stop at any point. Anything they do not know is
   left open, never guessed.
2. **One topic at a time.** Announce it ("Next: where the data comes from"). Ask one to three related
   questions in natural language. Where the answer is one of a few, offer the choices ("Monthly,
   quarterly, or on demand?"), with `AskUserQuestion` when the host has it. Offer a sensible default
   when something similar already has one ("The other report goes out on the third business day;
   the same here?").
3. **Read back.** Say what you understood as short plain sentences, one per thing ("The report goes
   out monthly, in English and French." "The analyst team owns it."). Then ask which way to go, in
   these words:
   - **Save it and move on**;
   - **Dig deeper**: edge cases, who else is involved, how it is measured, a counter-example;
   - **See it from someone else's side**: the other people this topic concerns (the data team,
     compliance, operations…).

   Save only when they choose to move on, and only what they confirmed.
4. **Save, behind the scenes**, then say the outcome in one sentence: "Saved." When the checks
   refuse something, say what in plain words and how to settle it ("I couldn't save that: nothing
   we have says where the currency comes from. Which column holds it, or shall we leave it open?").
   A warning that does not block is mentioned only when it matters to the person now.
5. **Progress, at the end of a topic**, not after every answer: what is now settled and what is still
   open, in what the questions ask, never their numbers ("That covers how the report runs. Still
   open: who signs off the disclaimer, and how long documents are kept.").
6. **Close.** A short recap: what was settled, what is left and who could answer it, what comes next.

## Behind the scenes

Everything in this section is for you. None of it is said to the person unless they ask.

### Preparing the topics

1. The project: `oto status --project <root>`. The packs it composes are in `project.config.json`.
2. The form: `oto ontology capture --project <root>` writes `capture.json`:
   - **sections**: the questions the vocabulary asks, grouped by who asks them (`sections[].who`):
     each is a topic. Each ask has its question (`asks[].question`, what to find out), why it is
     asked (`asks[].why`, why it matters to the person) and the item types it needs
     (`asks[].captures`);
   - **types**: each class with its fields (typed, enums as choices, `required`), its links (their
     targets and cardinality) and what it `requires`; every field and link carries `x-term`.

   Read it before the first question; regenerate it when the vocabulary changes. Turn each ask into
   a plain question; the required fields and links tell you what the answers must cover, and an
   enum's values become the choices you offer, in words.
3. When you do not understand an item, `kg_define <term>` (or `oto query define <term>`).
4. A source for what is said: the person's brief, notes or transcript in `inbox/` and `oto ingest`
   if there is one; otherwise the session itself, written as a dated document with the **capture**
   skill and ingested **before** the topic is saved, so the person's words are there to quote. Every
   fact cites a document, and the sentence in it that says the fact.

### Modes

- **Guided interview** (the default when little is written): topic by topic, as above.
- **Structure from notes**: read the material in full first; for each topic draft what the source
  supports, and ask only about what it leaves open. A fact the source does not contain stays open
  for the person, never a guess. The read-back says which sentences came from their notes.

### Saving a confirmed topic

Write the confirmed items as a capture file against the form:

```json
{"doc": "<document slug>", "as_of": "<the document's date>", "scope": "<what keeps these ids apart from another product's or report's>",
 "items": [{"type": "Requirement", "id": "FR3", "label": "Read every value from a finished column",
            "summary": "…", "fields": {"concerns": "data", "priority": "must"},
            "links": {"governs": ["report.monthly-statement"]},
            "where": "§3.2", "quote": "The product reads finished columns; it never computes."}]}
```

**Every item quotes its own sentence.** `quote` is the sentence of the document that says this item,
copied word for word (in an interview, the person's words as the session document holds them, not
your summary); `where` is the section or page. A fact said across a passage quotes its parts in order,
joined by `…`. A value read from a table or a diagram has no sentence: `where` names the table and
row, or the figure, and `quote` is left out. Never put the item's name or a paraphrase in `quote`:
`oto curate check` looks every quote up in its document and refuses one it cannot find there, and
reports, document by document, the items that quote nothing. To tighten an item saved earlier,
restate it unchanged with its exact `quote`: the new evidence is added beside the old.

Ids are stable (`FR3`, `P1`, `ADR-04`): a changed item keeps its id, so the change is a supersession,
not a second fact. Then:

```bash
oto curate start --project <root>                                         # once, when there is no candidate
oto curate propose --project <root> --from captures/<doc>-<group>.json   # refused if not a capture against the form
oto curate add --project <root> --from proposals/<doc>.json --dry-run
oto curate add --project <root> --from proposals/<doc>.json
oto curate check --project <root>
```

`oto curate start` refuses when a candidate already exists: keep adding to it. Never pass `--force`;
it discards the pending candidate. `propose` writes `proposals/<doc>.json` and names every link it
left out because its target is neither an item of the capture nor a node of the graph: ask the
person about the missing thing in plain words, then add it or fix the id.

### Reading the check

- **blocking**: a shape or a policy is broken (a link into nothing, a link over its `max`, a changed
  fact with no supersession). Fix the capture and propose it again; never force. Tell the person
  what is wrong in their terms (step 4 of the conversation).
- **gap**: a question the graph cannot answer yet, or a warning. It does not block; it is what step 5
  reports as still open.
- **SUSPECT**: a new id whose name matches an existing node. Ask the person whether it is the same
  thing as the one already known ("Is this the same Analyst team we talked about earlier?").

What is settled: `oto query --project <root> questions` (or `kg_questions`) says which questions the
graph now answers and which are open. Use it for step 5, in words. A question that stays open is open
work, not a block.

### Closing

`oto curate apply --project <root> --by "<the person>" --note "<what the topic made answerable>"`
promotes the candidate; `oto build --project <root>` makes it queryable. The skill that runs this one
decides when: after every topic, or after several.

## Guardrails

- **The form is the schema.** Something it does not ask for is not saved. If the person needs it,
  say plainly that this knowledge base does not record it yet and note it for whoever maintains the
  vocabulary (`oto ontology check`, then `accept`); never as a free-text note.
- **Never fill `validated_by`.** A person who knows the domain confirms a term; a capture records who
  said a fact, not that the vocabulary is right.
- **Never invent.** What the person did not confirm and no source says stays out.
