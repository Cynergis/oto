---
id: ADR-0008
title: A framework is a pack of the registry; the engine ships none
status: accepted
decided_on: 2026-10-29
decided_by: Chiheb Dkhil
governs: [workitem.epic-h]
---

# A framework is a pack of the registry; the engine ships none

## Context

ADR-0006 made an architecture framework a pack plus an adapter and moved CALM out of the engine's
arch module, into a pack of the engine: `oto/ontologies/calm` with its adapter at `oto/packs/calm.py`,
named `oto.packs.calm` in the manifest. ADR-0007 then drew the line between what ships with the
engine and what lives outside it, and placed every pack that describes the world on the inside:
the architecture, the domain model, the data layer, the people and their work. CALM stayed in by
that rule.

The rule misreads what a framework is. The architecture pack describes the world; CALM describes
how one organisation, FINOS, writes that description down. An adapter for it is a reader and writer
for someone else's notation, which OTO neither owns nor governs, and the next framework (C4) would
arrive from outside as "a second pack, not a change to the engine", in ADR-0006's words. The first
one being inside is the inconsistency the next reader of the repository trips over, as they did
over the factory. OTO's business is building and managing knowledge graphs and their ontologies; a
notation is neither.

Nothing technical holds it in. The adapter seam scans every pack on the machine for
`provides.adapters` and puts a pack's own `code/` on the import path before importing the module it
names (ADR-0007's seam, in 0.14.2). The adapter imports only the engine's public modules.

## Decision

An architecture framework is a pack of the registry, with its adapter in its own `code/`, installed like any pack and chosen through the adapter seam; the engine ships no framework adapter, and CALM, the first, moves to Cynergis/oto-registry as the `calm` pack.

## Consequences

**The calm pack.** `packs/calm` in the registry: the pack manifest, the `calm` ontology (release 2,
on `architecture`, adding no term) with the adapter as the module `oto_calm` in its `code/`, a
guide, the pack's tests with the FINOS trading-system fixture under its licence, and the plugin
files the registry generates. It is listed in the index and the marketplace as `calm@cynergis`,
installed with `/plugin install calm@cynergis` or `oto pack add calm`, found from any project that
composes `architecture` (it adds no term; `oto init --ontology architecture,calm` also records it), and
needs OTO 0.14.2, the first engine that loads a pack's code. The sandbox kit installs it with the other packs.

**The engine forgets it.** The pack, the adapter, the two CALM test files and the CALM fixtures
leave the engine's repository; no shipped manifest provides an adapter; `oto arch import` and
`export` on a machine with the engine alone say that no pack provides a framework. The engine's own
tests, which read a CALM model to exercise what the core does with any framework's model (the
document, the proposal through the gates, compile on merge, the code map), use a framework the tests
carry instead: the `plain` pack under `tests/fixtures/frameworks`, whose model is already the reified
model as a file. The documents name the registry's pack and this decision where they named the
engine's; the roadmap graph records the decision governing Epic H.

**What stays.** The reified model and its neutral attributes (`external_id`, `external_type`,
`external_payload`, `framework`), the adapter seam with `import`, `export` and `migrate`, the
`arch` command, the code map, compile on merge and the agent's context are the architecture pack's
and the core's, framework-neutral as ADR-0006 made them. The policy pack keeps `IamBinding` as a
class of its own, and the calm pack keeps exporting a binding node as a control when both are
composed.

**The other description packs.** The same argument applies to no other pack the engine ships: they
describe the world in OTO's own terms. The registry already carries nine of them as plugins; whether
the engine keeps shipping those copies is a question of distribution, not of what OTO is, and is
not decided here.
