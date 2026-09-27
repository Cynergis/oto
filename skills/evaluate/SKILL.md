---
name: evaluate
description: >-
  Validate an OTO knowledge graph against the documents it was built from: write a few gold
  questions per ingested document with the answer the document supports, run them against the
  graph, judge each answer for correctness and grounding, record the verdicts as feedback, and
  report what the graph gets right, wrong, and cannot answer. Use after a batch is authored and
  built, before `oto ingest complete`, or whenever someone asks "is the graph right?".
---

# Evaluate the graph against its own documents

A graph that looks complete is not evidence. This pass turns each ingested document into a few
questions the document itself answers, asks the graph, and judges the result. The deterministic
half is code: `oto bench` stores the questions with their provenance and scores citation,
coverage and time-awareness without a model. The judgment half is yours: writing questions worth
asking, and deciding whether an answer is right.

Two honesty rules make the numbers mean something:

- **The questions carry their provenance.** You wrote them, so the set's `_meta` says
  `authored_by_kind: model` and `audited_fraction: 0` until a person checks some. Every report
  prints that. Never raise the audited fraction yourself.
- **A judgment is recorded, not asserted.** Each verdict goes through `oto feedback record` with
  who judged it and what the right answer was, so it can be checked and promoted later.

## 1. Start or open the gold set

```bash
oto bench start --project <root>       # first time only; then set _meta honestly
oto bench validate --project <root>
```

Set `_meta.authored_by` to yourself by name and role, `authored_by_kind` to `model`,
`audited_fraction` to `0`.

## 2. Write a few questions per document

For each document in the run (`oto ingest runs`, or the proposals you authored), read the document
again and write **two to five** questions, more for a long document, fewer for a short one. Every
question needs something to grade against, and the graders reward different things:

| Type | Ask about | Grade against |
|---|---|---|
| `factual` | a fact the document states | `expected_entities`, `supporting_sources`, or an `answer` |
| `paraphrase` | the same fact in words the document does **not** use | `expected_entities` |
| `temporal` | whether a fact is current | `expected_status` |
| `temporal_change` | something the document changed, and when | `expected_status`, `answer` |
| `negative` | something a reader might assume the document says, and it does not | `answer: "absent"` |
| `multi-hop` | a question needing two relations | `expected_entities` |

Write them to `<root>/proposals/<slug>.questions.json`:

```json
{"source_doc": "<slug>", "questions": [
  {"question": "Who reviews a first notice of loss?", "type": "factual",
   "expected_entities": ["role.claims-adjuster"], "answer": "The claims adjuster, within two days."},
  {"question": "Which role signs off a disputed claim?", "type": "paraphrase",
   "expected_entities": ["role.claims-manager"]},
  {"question": "Does the handbook say who owns fraud referrals?", "type": "negative", "answer": "absent"}
]}
```

Then add them; the command refuses a question with nothing to grade against:

```bash
oto bench add --project <root> --from <root>/proposals/<slug>.questions.json
```

Include at least one `negative` and one `paraphrase` per document. Without negatives the set never
catches an invented fact; without paraphrases it never measures the lane where the graph is weakest.

## 3. Run the deterministic scores

```bash
oto bench run --project <root> --ablations
```

Read the report top to bottom: the provenance line first, then citation precision and recall,
coverage at k, entity hit, temporal score, then the threats to validity. The ablations show whether
the graph and the time-awareness each defend the metric they claim to.

## 4. Judge the answers

For each question, ask the graph the way a user would (the **query-knowledge** skill) and compare
with the answer the document supports. Four verdicts:

- **right**: the answer matches the document and cites it.
- **incomplete**: correct as far as it goes; the document says more.
- **unsupported**: the answer may be true, but the cited source does not say it, or nothing is cited.
- **wrong**: the answer contradicts the document.

Record every verdict that is not `right`, with the answer the document supports:

```bash
oto feedback record --project <root> --question "<the question>" --verdict wrong \
  --by "<you, as the judge>" --given "<what the graph said>" \
  --expected "<what the document says>" --source <slug>
```

A `wrong` or `unsupported` verdict on a fact is a curation problem, not an evaluation one: it goes
to the **curate** skill as a supersession or a missing citation. Do not fix the graph from here.

## 5. Report

Three lists, in this order, with counts:

1. **Right**, with the score line from the bench report.
2. **Wrong, unsupported or incomplete**, each with the document, the graph's answer, and the
   document's answer. These are the work.
3. **Cannot answer**, and why: a class that does not exist, a relation nobody declared, a document
   not ingested, a fact the document never states. This list is the most useful thing the
   evaluation produces.

Then say whether the run is fit to complete. A run with a `wrong` verdict outstanding is not; fix
the fact through curate, rebuild, re-run the questions, and only then `oto ingest complete`.

## Guardrails

- **Questions come from the document, not from the graph.** Writing questions the graph can answer,
  from the graph, proves nothing. Read the document.
- **Never mark the set audited.** Only a person who checked questions raises `audited_fraction`, and
  they set `audited_by`.
- **A judge's verdict is a claim.** Record it with your name; promote it into the gold set only once
  the expected answer is confirmed (`oto feedback promote`).
- **Do not fix facts from here.** Evaluation finds; curation changes.
