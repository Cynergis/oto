# Domain-driven design — the solution's model

Sits on `software-architecture` and so on `product`. The design of a product's solution for a builder
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
