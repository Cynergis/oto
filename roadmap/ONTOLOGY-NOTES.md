# Communication — messages beside the item they are about

On `work`: a `Message` is a fact in the graph, sent by someone to a person, team or role, about a
work item and the block it was sent from. It carries `from`, `body`, `sent`, `status` (pending until
read, replied, resolved) and `due`. Because it is a fact, it is dated, attributed and never edited,
and its answer can move the item it is about.

**The first message is a notification.** `oto work notify <item> --by <you> --at <date> [--due <date>]
[--body "..."]` writes one from the item's block to whom it waits on: the body carries the item, the
block's date, reason and author, then your words. `--to` tells someone else when the block waits on
a decision or an item rather than a person.

Questions (CM1–CM3, awaiting confirmation): what waits for a person (what a session opens with),
what has been said about an item and whether it is settled, which messages are overdue.

**v1 is for internal use.** Identity is whatever `--by` says or the git identity in the project;
anyone can send as anyone until the plugin connection (N2) and the audit log (N6) land. Replies,
resolution and the session-start inbox come next (N3, N4).

This is a first draft: edit it. Keep `regarding` pointing at the block as well as the item, because that
is where the reason lives.

---

## Inherited from `oto-core`

# OTO core

The base every shipped ontology extends, and the one to extend when no domain ontology fits. It
declares two things and nothing else:

- the **temporal vocabulary**: `asOf`, `validFrom`, `validTo`, `status`, `supersedes`,
  `supersededBy`, `sourceDoc`. These fields are what make a fact datable and supersedable, which
  is the property the whole system exists to protect. An ontology that extends this one inherits
  them and never merges them, so there is exactly one meaning of "current".
- **Document**, the class every fact cites, and `cites`, so a document can point at the document
  it rests on.

It is a first draft of nothing: a project started from `oto-core` alone has a vocabulary of one
class. Extend it in an ontology of your own (`"extends": ["oto-core"]` in `manifest.json`) and
declare the classes a real question needs. Edit it only to change what "a document" means for
every ontology at once.

---

## Inherited from `portfolio`

# Portfolio — what we build, who owns it, what we pursue

The base of the chain: `product`, `software-architecture`, `ddd` and `work` sit on it, so a role, a
team, an objective and a capability are one thing at every level, and a project composing four
packs holds one of each.

The executive's questions (PF1–PF10, confirmed by Chiheb Dkhil on 2026-10-07): which products we
build and where they stand; which objectives we pursue and which products pursue each; which
products depend on which; which capabilities we need, which product provides each and which has
none; what has no owner; which teams exist and what each owns; and, for a reader, where a product's
knowledge is: its query store, its site, the packs it is specified, designed and run with
(`store_url`, `site_url`, `packs` on the product).

What stays at the product level: what the product must do, for whom, under what rules, why.

---

## Inherited from `product`

# Product core — starter vocabulary

Exported from the project **Product core** (vocabulary version 1) with `oto ontology export`.

A first draft, not a finished model. **Edit it.** An ontology adopted unchanged is a worse outcome than no ontology, because nobody owns it and nobody recognizes the words.

In the source project, 20 of 20 classes had been confirmed by a named domain expert. That confirmation does not carry over: `validated_by` is empty here until someone who knows *your* domain confirms each class.

## Classes, and the question each answers

- **Product**: The thing a project sets out to build, software or not. The root every other class hangs off.
  - *Question:* Why does this product exist, and what is it? (A1)
  - *Why a class:* The root the whole vocabulary hangs off. Generic on purpose: one vocabulary every project starts from, a product being whatever the project sets out to build.
- **Role**: A function accountable for something: Product Owner, Sponsor, Lead Designer. Attach ownership and decisions to a role, never to a named person; the current holder is an attribute.
  - *Question:* Who owns it and who decides? (A4)
  - *Why a class:* Ownership questions are answered better by a role than a person, because roles are stable while people move; the holder is an attribute with history by supersession.
- **Persona**: A kind of user the product is for, or explicitly not for. Journeys, requirements and value propositions point at a persona.
  - *Question:* Who is it for, and who is it not for? (A2)
  - *Why a class:* Journeys, requirements and value propositions need something to point at, and the excluded audience must be a dated first-class fact, not a footnote.
- **ValueProposition**: One promise the product makes to a persona, and the problem it solves. The anchor every requirement, journey and success criterion traces to.
  - *Question:* Why does it exist, and what is the value proposition in one sentence? Which requirement serves which purpose? (A1, A3, D2)
  - *Why a class:* It is the traceability anchor: requirements, journeys and criteria trace to it, so an orphan requirement (failure F3) becomes a rule violation instead of folklore.
- **SuccessCriterion**: A measurable statement of what success looks like: a metric, a target, a date, an owner role.
  - *Question:* How do we know the product succeeded? (B2, failure F4)
  - *Why a class:* A target that changes needs history and an owner, and a product with none must be flaggable; an attribute list gives neither.
- **Requirement**: A stated need the product must satisfy, functional or otherwise. The unit a builder works from and a release scopes.
  - *Question:* What must the product do? What is in scope for the next release? (B3, B1)
  - *Why a class:* The unit a builder agent works from and a release scopes; it carries priority and kind, traces to a value proposition, and is what decisions are about.
- **Release**: A dated boundary of scope: what ships together. Requirements and features are in scope of, or excluded from, a release.
  - *Question:* What is in and out of scope for the next release, and what was the scope as of a past date? (B1, C3)
  - *Why a class:* Scope has to be scope OF something dated; edges to a release carry validFrom and validTo, so the boundary at any past date is readable.
- **Feature**: A user-visible capability the product is made of. Features nest through part_of, so an epic and a sub-feature are the same class at different depths.
  - *Question:* What is the product made of? (D4)
  - *Why a class:* Builders decompose the product into user-visible capabilities, each traced to a requirement; nesting through part_of lets epics and sub-features share one class.
- **UserJourney**: How a persona gets value, end to end: a trigger, ordered steps, an outcome.
  - *Question:* How does a user get value, step by step? (D1)
  - *Why a class:* Design and tests must follow the same path; the journey is the path, owned by a persona and delivering a value proposition.
- **JourneyStep**: One step of a user journey, with its own identity so a design decision, a requirement or a test can point at it.
  - *Question:* How does a user get value, step by step? (D1)
  - *Why a class:* A step has identity of its own: a design decision, a requirement or a test points at one step, which a list attribute on the journey cannot support.
- **Constraint**: A limit the product is built under: budget, platform, regulation, timeline. Imposed from outside, not chosen.
  - *Question:* What constraints is it built under? (B4)
  - *Why a class:* A constraint is imposed from outside and limits requirements and releases; it has a source and a lifecycle distinct from an assumption or a risk.
- **Assumption**: Something believed but not yet verified, on which a decision or requirement rests. Validated or invalidated over time.
  - *Question:* What assumptions is it built under, and which could invalidate the plan? (B4)
  - *Why a class:* An assumption is validated or invalidated over time and decisions rest on it, so its state change must propagate; that needs a node with history.
- **Risk**: A known way this can go wrong, including an external dependency whose failure would hurt. Mitigated, accepted or realised over time.
  - *Question:* What are the risks and external dependencies? (E1)
  - *Why a class:* A risk threatens something, is mitigated by something, and can block a release; an external dependency is modelled as a risk kind because what matters is what happens if it fails.
- **Decision**: A dated choice with its reason and evidence, made by a role. Settles what it is about, so nobody reopens it by accident.
  - *Question:* What did we decide about X, when, and why? (C1, failure F1)
  - *Why a class:* A decision has a date, a reason, evidence and a role that made it; a status field has none of those, and an agent needs to see a settled decision before reopening it.
- **OpenQuestion**: Something unresolved that a decision must settle. Raised, then resolved by a decision, or dropped.
  - *Question:* What is still open or unresolved? (C2)
  - *Why a class:* An open question is raised before any reason or evidence exists and is later resolved by a decision; keeping it separate lets an agent list what is open before building.
- **Document**: A source document in the corpus: a brief, a PRD, a UX spec, an architecture note, a transcript. Every fact cites one; a newer document supersedes an older one.
  - *Question:* Which document says so, and is it still current? Which artifacts describe the product, at which stage? (C4, D3, failure F2)
  - *Why a class:* Every fact cites a document, and a newer document supersedes an older one through the temporal vocabulary; kind and stage as attributes keep one class for all artifacts.
- **Objective**: A qualitative goal for a period, owned by a role and made measurable by success criteria. Objectives support higher objectives; that is strategic alignment.
  - *Question:* What are we trying to achieve this period, and are we on track? Where does this product sit in the strategy? (G1, G2; Gate 3 review)
  - *Why a class:* An objective is dated, owned and superseded, and criteria hang off it; strategic alignment is an objective supporting a higher one, which no attribute can express.
- **Scenario**: One concrete path through a requirement or a journey step: given, when, then. What a test verifies and what acceptance is judged on.
  - *Question:* What exactly must this do in this situation, and how do we test it? (G5; Gate 3 review)
  - *Why a class:* A scenario is the concrete path tests and acceptance run on, with its own preconditions and expected result; it must be pointable from a test and a requirement.
- **Policy**: A rule the product must obey that comes from outside it: business, compliance, data, security. Has an authority and a role that enforces it; distinct from a constraint, which limits resources.
  - *Question:* Which rules must the product obey, who enforces them, and what is affected? (G6; Gate 3 review)
  - *Why a class:* A policy prescribes behaviour and has an authority and an enforcing role, which a budget or timeline constraint does not; two people would populate a shared class differently.
- **Term**: A word with a definition in this product's language, cited and dated, so a changed meaning is superseded rather than argued about.
  - *Question:* What does this word mean here, who said so, and has the meaning changed? (G7; Gate 3 review)
  - *Why a class:* A definition needs a citation and a date so a changed meaning is superseded, which the search lexicon cannot hold; the lexicon is generated from terms instead.

## Relations

| Relation | Domain | Range | Meaning |
| --- | --- | --- | --- |
| `owned_by` | Product|Objective|Feature|SuccessCriterion|Risk|Requirement|Release | Role | The role accountable for this. Ownership sits on a role, not a person, so it survives people moving. |
| `decided_by` | Decision | Role | The role whose call it was. |
| `offers` | Product | ValueProposition | The promise a product makes. A product usually offers more than one. |
| `intended_for` | ValueProposition|UserJourney | Persona | The persona a value proposition or journey exists for. Requirements and features reach the persona through the value proposition they serve. Point at an excluded persona to say who it is deliberately not for. |
| `serves` | Requirement|UserJourney|Feature|ValueProposition | ValueProposition|Objective | The purpose this exists for: a requirement, journey or feature serves a value proposition; a value proposition serves an objective. The traceability spine an agent walks from a requirement up to the strategy. |
| `measures` | SuccessCriterion | Objective|ValueProposition | What a criterion tells you succeeded. |
| `part_of` | Feature|JourneyStep | Product|Feature|UserJourney | This belongs to that: a feature to its product or parent feature, a step to its journey. |
| `realises` | Feature | Requirement | The requirement a feature exists to satisfy. |
| `in_scope_of` | Requirement|Feature | Release | Ships in this release. Dated, so scope as of a past date is readable. |
| `excluded_from` | Requirement|Feature | Release | Explicitly not in this release. Recorded, not silently absent, so a builder sees the boundary. |
| `constrains` | Constraint | Product|Requirement|Release|Feature | What a constraint limits. |
| `relies_on` | Decision|Requirement|Release | Assumption | An assumption this rests on. If the assumption is invalidated, this must be revisited. |
| `threatens` | Risk | Product|Release|Requirement|Feature|SuccessCriterion | What a risk applies to. |
| `mitigated_by` | Risk | Decision|Requirement|Feature | What reduces a risk. |
| `about` | Decision|OpenQuestion | Product|ValueProposition|Objective|SuccessCriterion|Requirement|Release|Feature|UserJourney|JourneyStep|Scenario|Constraint|Policy|Risk|Persona | What a decision settles, or what an open question concerns. |
| `resolves` | Decision | OpenQuestion | The open question this decision closes. |
| `blocks` | OpenQuestion | Release | An unresolved question a release should not ship with. A risk threatens a release; it does not block it. |
| `documented_in` | Product|Role|Persona|ValueProposition|Objective|SuccessCriterion|Requirement|Release|Feature|UserJourney|JourneyStep|Scenario|Constraint|Policy|Assumption|Risk|Decision|OpenQuestion|Term | Document | The artifact that formally specifies this: a brief, a PRD, a UX spec. Distinct from source_doc, which is provenance: the document that introduced the fact into the graph, possibly a transcript. |
| `pursues` | Product | Objective | The objectives a product works towards. Usually derived (the product offers a value proposition that serves the objective); state it directly only when a document says so. |
| `supports` | Objective | Objective | A lower objective that contributes to a higher one. This is where strategic alignment is recorded. |
| `interested_in` | Role | Objective|Requirement|Release|Feature|Decision | What a stakeholder role must be consulted or informed about. |
| `exercises` | Scenario | Requirement|JourneyStep | The requirement or step a scenario is a concrete path through. |
| `enforced_by` | Policy | Role | The governance role that enforces a policy. |
| `defines` | Term | Product|ValueProposition|Objective|Requirement|Feature|UserJourney|Persona|Policy|Release|Scenario|Constraint|Risk | The entity a term is the name for, when there is one. |
| `applies_to` | Policy | Product|Requirement|Release|Feature|Decision | What a policy prescribes behaviour for. The governance edge: from here, enforced_by says who enforces it. |

## Growing it

```bash
oto ontology check --project <root>      # what a change breaks, and conformance
oto ontology rationale --project <root>  # which classes still lack a confirmed reason
oto ontology accept --project <root>     # record the vocabulary as the baseline
```

---

## Inherited from `software-architecture`

# Software architecture — starter vocabulary

How a product's solution is shaped. Sits on `product`: a requirement, a risk, a decision or a document is
the product's, and `satisfies` is the one edge from an asset back to the requirement it meets (SA8, SA17).

## What this shape is for

Most architecture documentation answers "what is this". This vocabulary is arranged to answer the
questions people actually ask under pressure:

- **"If we change this, what breaks?"** `consumes` is the edge that answers it. Coupling lives in the
  interfaces others depend on, not in the boxes. Record `exposes` and `consumes` before anything else.
- **"Who do I call?"** `owned_by` points at a `Team`, never a person. People move; the question does
  not.
- **"Why is it like this?"** The product's `Decision`, `about` the asset it shaped. Architecture without
  recorded reasons gets re-litigated every year.
- **"What is fragile?"** The product's `Risk`, with `threatens` and `mitigated_by` widened to the estate. A risk nobody can trace to a
  component is not actionable.
- **"What does the business lose?"** `Capability`, reached through `enables`. This is the only class
  a non-engineer will use, so keep its names theirs.

## Two writers to one store

`writes_to` is separated from `reads_from` on purpose. Two components writing one data store is the
most common quiet cause of an inconsistency nobody can explain. Once it is an edge, you can ask for it:

```bash
oto query --project <project> neighbors "<the store>"
```

## What is missing on purpose

No `Person`, no `Server`, no `Ticket`. Add them only when a question needs them. A vocabulary that
tries to be a configuration management database will be neither, and it will be out of date within a
month because nothing keeps it honest.

Consider instead pointing at what already holds that data. If your estate has a service catalog,
this graph should reference it, not copy it.

---

## Inherited from `work`

# Work — what is planned, by whom, blocked by what, deployed where

On `software-architecture` (and so on `product` and `portfolio`): a work item delivers a requirement,
a feature or a component; it is scheduled in a milestone or a release, assigned to a team or a role.

**Three states, never written on the item.** An item is `open`, `blocked` or `deployed`. Nobody sets
`state`: a `Transition` is appended (to which state, when, by whom; for a deployment, to which
environment), the previous transition is superseded, and the rule
`state-follows-the-current-transition` derives the state from the current one. An item with no
transition is open (the attribute's default). The superseded chain is the history: `oto query
entity <transition> --as-of <date>` says what the state was. `deployed` is set by events, a merged
pull request or a promotion, never by hand; `oto work set` refuses it.

**A block carries its context.** A `Block` is a transition to blocked that must carry a `reason`
and a `waiting_on` (a person, a team, an item, a decision, a question, a risk): the class requires
both, so a block without them is refused at the gate. `oto work set <item> --state blocked
--reason ... --waiting-on ...` writes one; `--state open` lifts it.

The delivery lead's questions (WK1–WK10, confirmed by Chiheb Dkhil on 2026-10-07): what is planned
for a milestone, what a team is working on and what of it is blocked, what blocks an item and who
owns the blocker, which requirements in scope nobody delivers, **which requirements slip if a
component is late** (the question that crosses every level), what is overdue, which decisions work
waits on, and whether a deployed item's requirement is satisfied in the design (trace closure).
Release 2 adds the board's questions (WK11–WK13, awaiting confirmation): what is blocked, since
when, why and on whom; what is deployed and where; where an item is now and who set it.

**Upgrading from release 1.** `planned` and `in-progress` read as `open`, `done` as `deployed`
(the attribute's `was`); a `dropped` item has no state and is retired instead. Items that still
assert a state keep it, and that asserted value wins over any transition: remove it when you start
recording transitions. There are no sprints; `estimate` stays optional and nothing runs on it.

This is a first draft of a delivery plan's vocabulary: edit it. The one thing to keep is the rule
that state comes from transitions, because the events of Epic B and the factory set it the same way
a person does.

---

Installed from the `communication` ontology by `oto init`. Edit the vocabulary in
`ontology.config.json`, then record your own reasoning here.
