---
name: ontology-interview
description: >-
  Design a domain vocabulary for an OTO project by interview, and record why each class exists.
  Produces ontology.config.json and ontology.rationale.json, then validates both with the tooling.
  Use when a project has no vocabulary yet, or when an existing one needs restructuring.
---

# Design a vocabulary by interview

The output is two files, and the second is the one people skip:

    ontology.config.json      the vocabulary
    ontology.rationale.json   why each class exists, and who confirmed it

A vocabulary with no recorded reasoning cannot be reviewed. A domain expert looking at sixteen class
names cannot tell a deliberate choice from an accident, so the review that matters never happens.

## The one rule: questions before nouns

The common failure is to list every noun in the domain, declare forty classes, and produce a model
nobody can hold in their head or agree on. It stops being used and starts being argued about.

So never ask "what things exist here". Ask **what questions must this answer**, write them down, and
derive classes from them. A class with no question behind it does not go in.

---

## Phase 0 — Read before asking

1. Run `oto survey --project <root>` for a map of the corpus: each document's headings, and the
   capitalised phrases and acronyms that recur across documents. Then read the source material in
   `build/documents/`. Do not skim it. The vocabulary must use the words the material uses, and the
   survey's phrases are candidates, not facts.
2. Note the words that recur and the words that are used two different ways by two different people.
   The second kind is where the modelling decisions are.

## Phase 1 — Collect the questions *(Gate 1)*

Ask for ten to twenty real questions the knowledge base must answer. Push for the ones asked under
pressure, not the tidy ones. Useful prompts:

- What did you last spend an afternoon trying to find out?
- What do you get asked that you cannot answer without asking three people?
- What went wrong because somebody did not know something?
- What do you need to know as of a past date, not just now?

Write them down verbatim. **Show the list and confirm it before designing anything.** If a question
is vague, ask what answer would look like. Stop when new questions stop producing new nouns.

If nobody is available to interview, or the person brought a specification, derive the questions
from the material: what does each document exist to tell a reader, what would a reader need to
look up, what in it changes over time. Label them as yours, and still show and confirm the list.
The **start** skill runs this path from a specification; **build-knowledge-base** from a corpus.

## Phase 2 — Pick a starting point

Run `oto ontology`. If one is close, start from it: `oto init --ontology <name>`. Editing something
concrete is faster and produces better models than facing an empty file.

Say which ontology you chose and why, or why none fit. `oto ontology show <name>` prints what an
ontology composes and what it changed on the way; read it before choosing.

If the project holds `INTERVIEW.md`, the ontology that seeded it wrote the questions a person who
knows this domain would ask first. Ask them in that order before your own, and record the answers
in the rationale like any other.

## Phase 3 — Derive the classes *(Gate 2)*

For each question, ask what kinds of thing the answer mentions. Then apply four tests to every
candidate class:

1. **Which question needs it?** If none, drop it.
2. **Is it a thing or a property of a thing?** If it has no identity of its own, no dates and no
   relationships, it is an attribute. Attributes are cheaper; prefer them.
3. **Is it one thing or two merged?** If two people would populate it differently, it is two.
4. **Does it need its own history?** Something that gets superseded, dated or reasoned about must be a
   node. A status field keeps no reason and no history.
5. **Is it a kind of another class?** When a question or a rule would be asked about several classes
   at once ("what does this team own", over systems, components and stores), declare the parent and
   mark each as `"subclass_of": ["Asset"]`: a question about the parent then covers them, and the
   parent's attributes apply to them. A parent that no question needs is a class nobody asked for.

Three decisions come up in almost every domain, so decide them explicitly:

- **A person, or a role?** Ownership questions are almost always answered better by a role, because
  roles are stable while people move. A named-person class is easy to build, hard to justify, and hard
  to remove once a corpus depends on it. Keep it only for people whose individual decisions must be
  traced.
- **An event, or the record of it?** A meeting and its transcript are different things with different
  dates. Merging them makes "what did we decide on the 14th" unanswerable.
- **A decision, or a status?** A decision has a date, a reason and evidence. A status has none of that.

**Show the proposed class list with the question each answers, and confirm it before writing files.**

## Phase 4 — Derive the relations

For each question, ask what has to be traversed to answer it. Then:

- Declare `domain` and `range` honestly, matching how the relation will really be used. A narrow
  declaration that the data violates is worse than a wide one, because `rdfs:domain` and `rdfs:range`
  are inference rules in the RDF export: a reasoner will infer the wrong type.
- Name an inverse only where someone would traverse the other way, and give it an `inverse_label`
  when its name does not read well from the other side.
- Every term is read by its name unless it carries a `label` (`part_of` reads "part of"; `url`
  needs `"label": "URL"`). Add `alt_labels` for the words the documents use for it, a `scope_note`
  where the boundary is easy to get wrong, and an `example`. A text is one string, or a map of
  language to string when the vocabulary declares `languages`.
- Give every relation a definition that says what it means, not what it is called.

Keep the temporal vocabulary the ontology ships. It is what makes supersession work.

## Phase 4b — Declare the attributes the questions filter or count on

An attribute is a value about a thing: a claim number, a state, a date, an amount. The four tests
in Phase 3 already decided which candidates are attributes rather than classes. Now declare the
ones a question will filter or count on, per class, with a type:

```json
"attributes": {
  "Claim": {"claim_number": {"type": "string", "definition": "The insurer's identifier."},
            "state": {"type": "enum:open|closed|denied", "definition": "Where the claim is in its handling."},
            "opened_on": {"type": "date", "definition": "When it was opened."}}
}
```

Types: `string`, `number`, `integer`, `boolean`, `date`, `list`, `enum:a|b|c`, or `scheme:<Name>`. Use
a scheme when people ask what a value means, translate it, or roll it up: declare it under
`"schemes"` with a `definition` and its `concepts`, each with a `label`, a `definition` and, where one
is a kind of another, a `broader` concept. Keep an enum for codes whose meaning needs no words. A present value
must fit the type; absent is always allowed. A class that declares attributes reports any key it
carries that nobody declared, so two drafters cannot call the same thing `state` and
`status_code`. Declare what "how many X where Y" needs, and nothing speculative: an undeclared
attribute still works, it is just unchecked.

## Phase 4c — Declare the rules the questions need

Some answers are one hop further than any document states: a risk to a component is a risk to
its system; a consumer of an interface depends on its provider. And some things a policy forbids:
a decision with no document behind it. Declare these in `rules.json`, each with a `why`, and
never fill `validated_by` yourself:

```json
{"rules": [
  {"id": "risk-reaches-system", "kind": "derive",
   "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
   "then": {"edge": ["r", "threatens", "s"]},
   "why": "Impact questions need the system; documents state only the component.", "validated_by": ""},
  {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
   "when": [{"node": "d", "type": "DecisionRecord"}, {"not_edge": ["d", "documented_in", "*"]}],
   "then": {"flag": "an architecture decision must cite the document that records it"},
   "why": "A decision nobody can open is a rumour.", "validated_by": ""}]}
```

The tests for a rule are the tests for a class: which question needs it, and would a domain
expert recognise it. A derived fact is marked as derived in every answer and explained on
request, so a rule that is wrong is visible; a rule nobody needed is just noise. Derivation rules
are positive; only policy rules may say `not_edge` or `not_node`. `oto rules check` dry-runs the
set and shows what each rule would derive or flag.

## Phase 4d — Write the questions so they run, and the shapes they imply

A question in prose is a promise; a question that runs is a check. Write each Gate 1 question
into `questions.json`, in the pattern language of the rules, so `oto ontology check` can say
whether the graph answers it and `oto curate check` can refuse a change that would make it
unanswerable:

```json
{"questions": {
  "CQ3": {"who": "claims handler",
          "question": "Which coverage is claim $CLAIM paid under, and what limit applies?",
          "why": "A payment charged to the wrong coverage is the costliest error in handling.",
          "validated_by": "",
          "params": {"CLAIM": {"type": "Claim"}},
          "ask": {"when": [{"edge": ["p", "part_of_claim", "$CLAIM"]}, {"node": "p", "type": "Payment"},
                           {"edge": ["p", "charged_to", "c"]}, {"node": "c", "type": "Coverage"}],
                  "select": ["p.label", "c.label", "c.limit"]},
          "gate": "non_empty",
          "gaps": {"when": [{"node": "$CLAIM", "type": "Claim", "where": {"state": "open"}}],
                   "say": "the claim is open and nothing has been charged yet"}}}}
```

- `ask.when` is a rule's `when`; `select` names bound variables, `var.label`, `var.type` or
  `var.<attribute>`; a `$NAME` is a parameter bound to an entity when the question is asked.
- The **gate** says what an empty answer means, and choose it with care: `non_empty` means every
  entity of the parameter's class must answer, and `oto curate check` blocks a candidate where one
  does not. Use it for structural invariants (a claim claims under a policy); use `any` with a
  `gaps` explanation for what may legitimately be absent yet (a claim not yet decided); use
  `empty` for a policy (which closed claims carry no decision?).
- **Every class, relation and attribute must be cited by a question** (its patterns, its
  parameters, or a `terms` list). `oto ontology check` lists the terms no question cites, and
  `oto ontology accept` refuses the vocabulary until they are. This is the discipline of Phase 1
  made executable: a term no question needs is a term nobody can say the purpose of.
- Show the questions to the user with the classes: `oto query questions` after a build says which
  the sample graph answers, and `oto query ask CQ3 CLAIM="<a claim>"` shows one answer.

The same questions imply **shapes**, declared beside the terms in `ontology.config.json`: a
relation's `min` and `max` (`"charged_to": {..., "min": 1, "max": 1}`: a payment is charged to
exactly one coverage), an attribute's `"required": true`, a class's `"requires": ["part_of"]`.
Declare a shape only where a question would be unanswerable without it; `oto curate check`
refuses a candidate that breaks one, and tightening one later is a breaking change. A policy
rule may name the question it protects (`"answers": "CQ3"`), so its finding says what it would
leave unanswerable.

## Phase 5 — Write the files

1. Write `ontology.config.json`: `ontology_version: 1`, `strict_domains: false`, classes, properties,
   temporal. Every declaration is an object, and the build refuses any other form:

   ```json
   "classes": {"Claim": {"definition": "A request for payment under a policy."}},
   "properties": {"filed_by": {"domain": "Claim", "range": "Party|Organization", "inverse": "filed",
                               "definition": "Who filed the claim."}}
   ```

   `domain` and `range` name one class or a union written `A|B`; leave `range` or `inverse` out
   when there is none.
2. Write `ontology.rationale.json`. For every class, record:
   - `question` — what it exists to answer, in the asker's words
   - `why` — why it is its own class rather than an attribute or a merge
   - `alternatives` — what was considered and rejected, and why
   - `validated_by` — **leave empty.** It is filled only when a person who knows the domain has
     actually confirmed the entry. Never guess it, and never put your own name in it.
3. Add a relation rationale only where the definition does not already say enough.
4. Write `questions.json` (Phase 4d): the Gate 1 questions, each with `who`, `why`, an `ask` that
   runs, a `gate`, and `validated_by` empty until the person who asks it confirms it.

## Phase 6 — Validate with the tooling, not by eye

```bash
oto ontology rationale --project <project> --strict   # every class has a recorded reason
oto rules check --project <project>                  # the rules validate and derive what you expect
oto build --project <project>                        # the integrity gate must be clean
oto ontology check --project <project>               # conformance, shapes, policy findings, the questions
                                                     # the graph cannot answer, the terms no question cites
oto query --project <project> questions              # every question, and whether the graph answers it
oto ontology accept --project <project>              # record vocabulary, rules and questions as the baseline;
                                                     # refuses while a term is cited by no question
```

Fix what these report before showing anyone. `oto ontology check` reporting zero violations on day
one matters: once it reports hundreds, people stop reading it.

A vocabulary that passes these can become a starter for the next project in the domain:
`oto ontology export --project <project> --name <name>`. It refuses while any class lacks a
recorded reason, which is one more reason to write the rationale now.

## Phase 7 — Hand it to a domain expert *(Gate 3)*

Send the expert the rationale file, not the vocabulary. It reads as a list of questions and answers,
which is reviewable; a class list is not.

Ask them for three things:

1. Rename anything whose name they would not use.
2. Name what is missing.
3. Name what here is really two things.

When they confirm an entry, fill `validated_by` with their name and the date. Report coverage plainly:
"4 of 16 classes confirmed, 12 not yet" is an honest statement about a draft. "The model is validated"
is not.

---

## Guardrails

- **A class with no question behind it does not go in.** This is the whole discipline, and the
  engine enforces it: a term no question in `questions.json` cites is refused by `oto ontology accept`.
- **A `non_empty` gate is a promise about every instance.** Choose `any` with a `gaps` line for what
  may legitimately be absent; a gate set too strict blocks every curator after you.
- **Nine classes will feel too few.** Add the tenth when a question needs it, and write down which.
- **Never fill `validated_by` yourself.** It is the only field that says a human checked, and a guessed
  value makes the whole record worthless.
- **Never claim a model is validated because it looks reasonable.** Count the confirmed entries.
- **Do not invent jurisdiction-specific or regulatory classes.** A plausible-sounding wrong class is
  worse than a missing one. Confirm them, and cite the instrument.
- **Bump `ontology_version` before removing a class or relation, or narrowing a domain or range.** Then
  run `oto ontology accept`.
