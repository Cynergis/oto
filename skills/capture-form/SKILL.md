---
name: capture-form
description: >-
  Fill an OTO project's capture form with a person: read capture.json (the questions the
  vocabulary asks, grouped by who asks them, and the items each needs), ask in small groups, draft
  the items, and send every confirmed group through the curate gates as a capture file (propose,
  add, check, apply), reporting which questions the graph now answers. Guided interview, or
  structure-from-notes. Use when someone wants to "capture against a pack", "fill the form",
  "interview me for this pack", or when a pack's or a studio's skill says to run the capture form.
---

# Fill the capture form

The vocabulary knows what to ask. This skill asks it and contributes what the person confirms,
group by group, never at the end. You are a facilitator; never invent content the person has not
confirmed. A pack's or a studio's skill usually runs this one and adds what its domain needs on top
(the order of the groups, what you draft yourself, a menu at each confirmation, when to close).

This is not the **capture** skill: that one writes a spoken statement into the inbox as a source
document. This one turns answers into facts through a form.

## 1. The form

1. The project: `oto status --project <root>`. The packs it composes are in `project.config.json`.
2. The schema: `oto ontology capture --project <root>` writes `capture.json`, the form:
   - **sections**: the competency questions grouped by who asks them (`sections[].who`), each
     ask with its question, why it is asked, and the item types it needs (`asks[].captures`);
   - **types**: each class with its fields (typed, enums as choices, `required`), its links (the
     targets they may point at, and their cardinality) and what it `requires`; every field and
     link carries `x-term`.

   Read it before the first question. Regenerate it when the vocabulary changes; do not work from
   a remembered list.
3. When you do not understand an item, `kg_define <term>` (or `oto query define <term>`). Ask the
   person in their words, not the ontology's.
4. A source for what is said: the person's brief, notes or transcript in `inbox/` and `oto ingest`
   if there is one; otherwise the session itself, written as a dated document with the **capture**
   skill. Every fact cites a document.

## 2. Modes

- **Guided interview** (the default when little is written): group by group, as below.
- **Structure from notes**: read the material in full first; for each group draft what the source
  supports, mark gaps and assumptions, and ask only to fill the gaps. A fact the source does not
  contain is a `TODO` for the person, never a guess.

## 3. The loop, per group

Take the sections in the order the form lists them. For each ask:

1. Say what it captures and why (`asks[].question`, `asks[].why`), and name the item types it
   needs with their required fields and links; offer an enum's choices and a link's targets.
2. Ask a few related questions at a time, 1–4 (`AskUserQuestion` when the host has it). Offer a
   default when a similar entity in the graph already has one ("the other report runs on the third
   business day; the same here?").
3. If the person does not know, do not guess and do not block: leave the item out and go on. The
   check carries it as an open question; note who can answer it if they say.
4. Draft the items and show them as items: type, id, label, fields, links, and where it was said.
   Correct what the person changes. Contribute only what they confirm.

## 4. Contribute each confirmed group

Write the confirmed items as a capture file against the form:

```json
{"doc": "<document slug>", "as_of": "<the document's date>", "scope": "<what keeps these ids apart from another product's or report's>",
 "items": [{"type": "Requirement", "id": "FR3", "label": "Read every value from a finished column",
            "summary": "…", "fields": {"concerns": "data", "priority": "must"},
            "links": {"governs": ["report.fund-profile-balanced"]},
            "where": "§3.2", "quote": "The product reads finished columns; it never computes."}]}
```

Ids are stable (`FR3`, `P1`, `ADR-04`): a changed item keeps its id, so the change is a supersession,
not a second fact. Then:

```bash
oto curate start --project <root>                                         # once, when there is no candidate
oto curate propose --project <root> --from captures/<doc>-<group>.json   # refused if not a capture against the form
oto curate add --project <root> --from proposals/<doc>.json --dry-run
oto curate add --project <root> --from proposals/<doc>.json
oto curate check --project <root>
```

`oto curate start` refuses when a candidate already exists: keep adding to it. Never pass
`--force`; it discards the pending candidate. `propose` writes `proposals/<doc>.json` and names
every link it left out because its target is neither an item of the capture nor a node of the
graph: tell the person, and add the target or fix the id.

## 5. Read the check in the engine's words

- **blocking**: a shape or a policy is broken (a link into nothing, a link over its `max`, a
  changed fact with no supersession). Fix the capture and re-propose; never force.
- **gap**: a question the graph cannot answer yet, or a warning. Tell the person; it does not
  block the conversation.
- **SUSPECT**: a new id whose name matches an existing node. Ask the person: one thing or two?

Then the gate: `oto query --project <root> questions` (or `kg_questions`) says which questions the
graph now answers and which are open, with the gap. Report it as "the graph answers N of M; open:
…". A question that stays unanswered is open work, not a block.

## 6. Close

`oto curate apply --project <root> --by "<the person>" --note "<what the group made answerable>"`
promotes the candidate; `oto build --project <root>` makes it queryable. The skill that runs this
one decides when: after every group, or after several.

## Guardrails

- **The form is the schema.** A field or link it does not list is not captured. If the person
  needs it, that is a vocabulary change (`oto ontology check`, then `accept`), not a free-text note.
- **Never fill `validated_by`.** A person who knows the domain confirms a term; a capture records
  who said a fact, not that the vocabulary is right.
- **Never invent.** What the person did not confirm and no source says stays out of the capture.
