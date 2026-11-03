---
name: ontology-interview
description: >-
  Design a domain vocabulary by interview, in an ontology workspace (a pack in the making), and
  record why each class exists. Produces the pack's ontology/<name>/ files: the terms, the
  rationale, the questions the graph must answer, the rules and a small sample, then holds them to
  the pack's gates (oto pack check --strict, oto pack try) and releases them (oto pack publish). Use
  when an ontology is to be made, extended or restructured. A knowledge project's vocabulary is the
  packs' and is not edited there: this skill opens or finds the workspace instead.
---

# Design a vocabulary by interview

An ontology is made once and used many times, so it is made in a place of its own: an **ontology
workspace**, a pack in the making, with a trial project beside the deliverable. The output is the
pack's files, and the second is the one people skip:

    ontology/<name>/ontology.config.json      the vocabulary
    ontology/<name>/ontology.rationale.json   why each class exists, and who confirmed it
    ontology/<name>/questions.json            what a graph in this vocabulary must answer
    ontology/<name>/rules.json                what is derived, and what a policy forbids (optional)
    ontology/<name>/sample.graph.json         a small graph every question answers from

A vocabulary with no recorded reasoning cannot be reviewed. A domain expert looking at sixteen class
names cannot tell a deliberate choice from an accident, so the review that matters never happens.

A **knowledge project** started from a pack does not define its vocabulary: the file is derived
from the packs it composes, written by the engine, and `oto ontology check` refuses a hand edit.
When someone asks for a class in such a project, the work is here, in the pack's workspace, or in a
new pack that extends it; never in the project's file.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say question numbers, ids, class or
  field names, file names or commands, and never paste what a command printed.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to do, ask a few questions at a time,
  read back what you understood in plain sentences, confirm, then say what is next.

## The one rule: questions before nouns

The common failure is to list every noun in the domain, declare forty classes, and produce a model
nobody can hold in their head or agree on. It stops being used and starts being argued about.

So never ask "what things exist here". Ask **what questions must this answer**, write them down, and
derive classes from them. A class with no question behind it does not go in.

---

## Phase 0 — The workspace, and the reading

1. Find or open the workspace. Three cases:

   ```bash
   oto pack new <name> --to <dir> [--extends <base,...>] [--domain <slug>]   # a new ontology: a starter to fill, on oto-core or on the bases named
   oto pack new <name> --to <dir> --from-project <project>                   # a project that grew its own vocabulary: it becomes a pack (the bridge)
   cd <the pack's repository>                                                # an ontology that already has a workspace: work there
   ```

   The workspace is a directory of its own, a git repository: the pack (`manifest.json`,
   `ontology/<name>/`, `skills/`, `views/`), a `trial/` knowledge project beside it, and two
   workflows that run the gates on every pull request and publish on a tag. `oto pack new` without
   a vocabulary says the pack is not yet usable; that is this skill's job.

   Started in a knowledge project whose vocabulary is derived (`oto status` says `derived from
   <pack>`), do not edit it: find that pack's workspace, or open a new pack that extends it
   (`--extends <pack>`), and say so to the person.

2. Read before asking. Sample documents go into the trial project, which is where documents are
   read and the vocabulary is tried:

   ```bash
   oto ingest --project <workspace>/trial                  # the documents, into the trial's corpus
   oto survey --project <workspace>/trial                  # a map: headings, recurring phrases and acronyms
   ```

   Then read the material in `<workspace>/trial/build/documents/`. Do not skim it. The vocabulary
   must use the words the material uses, and the survey's phrases are candidates, not facts. Note
   the words that recur and the words that are used two different ways by two different people: the
   second kind is where the modelling decisions are. A client's documents may not be committed to
   the workspace's repository; the trial's inbox and corpus are for reading, and the workflow's
   publishability scan says so.

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

## Phase 2 — Pick what to rest on

Run `oto pack list` and `oto ontology list`. An ontology is never edited into a copy; it is
extended. If a pack is close, the new vocabulary rests on it: `oto pack new <name> --to <dir>
--extends <pack>` embeds the base beside the new terms, and a project later composes both. If the
pack is right but a term is missing or wrong, the work belongs in that pack's own workspace, as a
release of it. Only a domain nobody has described starts on `oto-core` alone.

Say which base you chose and why, or why none fit. `oto ontology show <name>` prints what an
ontology composes and what it changed on the way; read it before choosing.

If the base carries `INTERVIEW.md`, the ontology that seeded it wrote the questions a person who
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
- A pack that extends another may widen a relation of its base, never give it a second meaning: a
  relation name declared twice with two meanings is a composition error.

The temporal vocabulary comes from `oto-core`, which every ontology rests on. It is what makes
supersession work; nothing here redeclares it.

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
a decision with no document behind it. Declare these in the pack's `rules.json`, each with a `why`,
and never fill `validated_by` yourself:

```json
{"rules": [
  {"id": "risk-reaches-system", "kind": "derive",
   "when": [{"edge": ["r", "threatens", "c"]}, {"edge": ["c", "part_of", "s"]}],
   "then": {"edge": ["r", "threatens", "s"]},
   "why": "Impact questions need the system; documents state only the component.", "validated_by": ""},
  {"id": "decision-is-documented", "kind": "policy", "severity": "warn",
   "when": [{"node": "d", "type": "Decision"}, {"not_edge": ["d", "documented_in", "*"]}],
   "then": {"flag": "an architecture decision must cite the document that records it"},
   "why": "A decision nobody can open is a rumour.", "validated_by": ""}]}
```

The tests for a rule are the tests for a class: which question needs it, and would a domain
expert recognise it. A derived fact is marked as derived in every answer and explained on
request, so a rule that is wrong is visible; a rule nobody needed is just noise. Derivation rules
are positive; only policy rules may say `not_edge` or `not_node`. `oto rules check --project
<workspace>/trial` dry-runs the set against the trial and shows what each rule would derive or flag.

## Phase 4d — Write the questions so they run, and the shapes they imply

A question in prose is a promise; a question that runs is a check. Write each Gate 1 question
into the pack's `questions.json`, in the pattern language of the rules, so `oto pack check` can say
whether the sample answers it and a project's `oto curate check` can refuse a change that would make
it unanswerable:

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
  parameters, or a `terms` list). `oto pack check` lists the terms no question cites and refuses the
  pack until they are. This is the discipline of Phase 1 made executable: a term no question needs
  is a term nobody can say the purpose of.

The same questions imply **shapes**, declared beside the terms in `ontology.config.json`: a
relation's `min` and `max` (`"charged_to": {..., "min": 1, "max": 1}`: a payment is charged to
exactly one coverage), an attribute's `"required": true`, a class's `"requires": ["part_of"]`.
Declare a shape only where a question would be unanswerable without it; `oto curate check`
refuses a candidate that breaks one, and tightening one later is a breaking change. A policy
rule may name the question it protects (`"answers": "CQ3"`), so its finding says what it would
leave unanswerable.

## Phase 5 — Write the files

All under `<workspace>/ontology/<name>/`:

1. `ontology.config.json`: `ontology_version: 1`, `strict_domains: false`, classes, properties,
   attributes. Every declaration is an object, and the build refuses any other form:

   ```json
   "classes": {"Claim": {"definition": "A request for payment under a policy."}},
   "properties": {"filed_by": {"domain": "Claim", "range": "Party|Organization", "inverse": "filed",
                               "definition": "Who filed the claim."}}
   ```

   `domain` and `range` name one class or a union written `A|B`; leave `range` or `inverse` out
   when there is none. The bases the pack extends are embedded beside it; the file declares only
   what this pack adds.
2. `ontology.rationale.json`. For every class and relation, record:
   - `question` — what it exists to answer, in the asker's words
   - `why` — why it is its own class rather than an attribute or a merge, in a sentence or two
   - `alternatives` — what was considered and rejected, and why
   - `validated_by` — **leave empty.** It is filled only when a person who knows the domain has
     actually confirmed the entry. Never guess it, and never put your own name in it.
3. `questions.json` (Phase 4d): the Gate 1 questions, each with `who`, `why`, an `ask` that runs,
   a `gate`, and `validated_by` empty until the person who asks it confirms it.
4. `sample.graph.json`: a small graph, a handful of nodes in the pack's own classes with the edges
   between them, written for the purpose and naming nobody real, from which every question answers.
   It is what a project started from the pack sees first, and what `oto pack check` asks the
   questions against. Never a client's graph.
5. `README.md`: what the domain is and how to read a graph in this vocabulary; `manifest.json`'s
   `summary` in one line, and a `namespace` of the organisation's own.
6. `manifest.json`'s `routes`, optional: the policy a project on the pack starts with for how
   changes reach its `main` ([ADR-0013](../../docs/adr/0013-three-routes-into-main.md)). Ask the
   domain owner, in their words, which changes may land on the word of the person who made them,
   which a second person must see, and what a meeting transcript may add with nobody looking:

   ```json
   "routes": {
     "allowed": ["session", "reviewed", "guardrailed"],
     "session": {"classes": ["Card", "Move"]},
     "guardrailed": {"from": "inbox/transcripts", "classes": ["Blocker"], "max_facts": 40,
                     "additive_only": true, "attributed": true}
   }
   ```

   `allowed` always holds `reviewed`; leave `guardrailed` out and every transcript goes to a
   person. `session.classes` and `guardrailed.classes` name classes the pack declares. The pack
   sets the policy, never the route a change takes: that is derived from what the pull request
   carries. `oto pack check` validates the section and `oto pack show` prints it; a project derives
   it at `oto init --pack` and may override a key by writing it.

## Phase 6 — Validate with the tooling, not by eye

```bash
oto pack check <workspace> --strict      # the vocabulary's shapes; every term cited by a question; the sample answers every question;
                                         # a reason and a confirmation per term; nothing that names a client
oto pack try <workspace>                 # the trial's vocabulary written from the pack, built; its questions asked against the trial's facts
oto query --project <workspace>/trial questions    # every question, and whether the trial answers it
oto rules check --project <workspace>/trial        # the rules validate and derive what you expect
```

Fix what these report before showing anyone. A check reporting zero problems on day one matters:
once it reports hundreds, people stop reading it. The trial's documents are the pack's test corpus:
author a proposal or two from them through the curate gates, so the vocabulary is tried against
facts someone actually wrote down, not only against the sample.

The workspace's `pack-check.yml` runs the strict check on every pull request, so the repository
holds the gate.

## Phase 7 — Hand it to a domain expert *(Gate 3)*

Send the expert the rationale file, not the vocabulary. It reads as a list of questions and answers,
which is reviewable; a class list is not.

Ask them for three things:

1. Rename anything whose name they would not use.
2. Name what is missing.
3. Name what here is really two things.

When they confirm an entry, fill `validated_by` with their name and the date. Report coverage plainly:
"4 of 16 classes confirmed, 12 not yet" is an honest statement about a draft. "The model is validated"
is not. `oto pack check --strict` refuses the pack while a term lacks a confirmation, which is the
release's gate: an ontology is released confirmed, or not released.

## Phase 8 — Release

```bash
oto pack publish --from <workspace> --to <registry url> --note "<what this release changes>"
```

The registry carries the pack, raises its release, tags it, and lists it in the marketplace; the
workspace's `pack-publish.yml` does the same on a tag. From there a team starts a project on it
(`oto pack add <name>`, `oto init --pack <name>`), its vocabulary derived from the pack, and a later
release reaches them through `oto status`, `oto ontology diff` and `oto ontology update`. The trial
project and the workflows stay behind; the pack is the deliverable.

---

## Guardrails

- **A class with no question behind it does not go in.** This is the whole discipline, and the
  engine enforces it: a term no question in `questions.json` cites is refused by `oto pack check`.
- **The vocabulary is made in the workspace, never in a knowledge project.** A project started
  from a pack derives its vocabulary and refuses a hand edit; a missing term is a release of the
  pack, or a pack that extends it.
- **A `non_empty` gate is a promise about every instance.** Choose `any` with a `gaps` line for what
  may legitimately be absent; a gate set too strict blocks every curator after you.
- **Nine classes will feel too few.** Add the tenth when a question needs it, and write down which.
- **Never fill `validated_by` yourself.** It is the only field that says a human checked, and a guessed
  value makes the whole record worthless.
- **Never claim a model is validated because it looks reasonable.** Count the confirmed entries.
- **The sample names nobody real.** It is published with the pack; a client's data never is, and
  the publishability scan refuses a pack that names a client term.
- **Do not invent jurisdiction-specific or regulatory classes.** A plausible-sounding wrong class is
  worse than a missing one. Confirm them, and cite the instrument.
- **Bump `ontology_version` before removing a class or relation, or narrowing a domain or range.** A
  project on the pack sees it as a breaking change in `oto ontology diff` before it updates.
