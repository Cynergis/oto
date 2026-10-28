# Domain-driven design — the solution's model

Sits on `architecture` (and so on `software-architecture` and `product`): a context's `deployed_as`
component and its architecture node are one node, with one `external_id` (roadmap I1). The design of a product's solution for a builder
agent: **strategic** (subdomains, bounded contexts, the context map), **event storming** (events,
commands, reactions, read models, external systems) and **tactical** (aggregates, entities, value
objects, business rules, domain services).

What it does not carry, because the product does: the product itself and its purpose (`Objective`,
`ValueProposition`), the people (`Persona`, `Role`), the obligations (`Requirement`, `Policy`), the
acceptance (`Scenario`), the language (`Term`), the reasons (`Decision`) and the hotspots
(`OpenQuestion`). What the estate carries: the `Team` that owns a context and the `Component` that
`deployed_as` points at.

The one word that changed: the event-storming *policy* ("whenever this event, then that command")
is `Reaction` here, because the product's `Policy` is a rule imposed from outside, and a project
composes both.

Three traces a builder walks: `UseCase satisfies Requirement` (DD4, DD24), `Scenario exercises
UseCase` (DD5), `BoundedContext deployed_as Component` (DD2). Readiness is declared on use cases,
contexts, commands and aggregates and checked across them (DD23).

Generalised from `ddd-kyc` @2 on 2026-10-07; the KYC case tool stays where it was.

**Filling it (roadmap I2).** Two ways in, both through the gates. The capture-form skill interviews
a person against the vocabulary. `oto ddd storm --from board.json --at <date> [--context <node id>]`
reads an event-storming board (stickies by kind: event, command, actor, aggregate, policy, read model,
external system, hot spot, each pointing at others by their text) into a document in the corpus and a
capture; `oto curate propose --from captures/storm-<slug>.json` makes the proposal, and `add`, `check`
and `apply` take it. An aggregate gets the root entity the vocabulary requires, named after it; a
command with no aggregate and a sticky that points at nothing are said before the gates, never
invented. Readiness is a decision with `draft` as its default: nothing the board says makes an
element ready. The analyst signs off on the graph itself, `oto decide <node> readiness=ready --by
<name> --at <date>`, an assertion by them applied under the gates, in place of a sign-off screen
(Epic D); DD23 then names a ready context whose aggregate or command is still a draft.
