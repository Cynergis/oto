---
id: ADR-0006
title: The core is the knowledge graph, its tools and its deploy; frameworks and domains are packs
status: accepted
decided_on: 2026-10-28
decided_by: Chiheb Dkhil
governs: [workitem.epic-c, workitem.epic-e, workitem.epic-h, workitem.epic-i, workitem.epic-j, workitem.epic-m, workitem.epic-n]
---

# The core is the knowledge graph, its tools and its deploy; frameworks and domains are packs

## Context

The roadmap delivered fourteen epics as one product. Six of them (C data, E policy, H
architecture, I domain, J factory, M work, N communication) arrived as ontology packs, which is
right, but their tools arrived as engine modules: the policy compiler, the IAM derivation, the work
commands, the storming importer, the factory's commands, and a CALM importer and exporter whose
attribute names (`calm_id`, `calm_type`, `calm_header`) are written into the architecture pack.
A build stage list and a command list in the engine name them all. A project that uses none of
them is unaffected at run time, because every one is gated on its pack being in the vocabulary,
but the engine ships them all and the documents present them as the product.

Two consequences follow. A reader cannot tell what OTO is from what it can also do. And an
organisation that writes its architecture in C4 rather than CALM, or wants no architecture
framework at all, would have to change engine code and a pack's vocabulary, when the engine's
own tools on the architecture (the code map, impact, the agent's context) need no framework.

## Decision

OTO's core is the knowledge graph's lifecycle with its tools, the estate and the reified model it is described in, and the deploy of the graph; an architecture framework is a pack plus an adapter, and a domain feature is a pack plus its tools, loaded only when the pack is composed in the project.

## Consequences

**Core.** The project and its scaffolding; ingest and capture into the corpus; curate with its
gates and evidence checks; decide; the audit chain; graph snapshots and versions; build with its
compile stages and store targets; query; serve with the explorer, the reader and the workbench;
the ontology tooling (compose, widen, import, export, diff, lexicon, packs, registry, catalog);
decisions compiled from records; federation across graphs; and deploy, which publishes the built
graph and promotes it through environments with approvers, because what is deployed is the graph.
Core also holds the base vocabulary every pack extends, the estate (a system, a component, a
store, an interface, an environment, a repository, a decision, a role, a team), and the reified
model on top of it: that a relationship, a control and a flow can be nodes of the graph, so a flow
can walk relationships in order and a control can safeguard them, with requirements, evidence,
code modules, commits, change proposals and contracts beside them. That is a graph modelling
decision, not a framework's; CALM and C4 both map onto it. The tools that read only that model,
the code map, compile on merge, impact and the context an agent reads before it edits, are core.

**A framework is a pack plus an adapter.** CALM is the first: a pack that carries what CALM adds
to the reified model, and an adapter that imports and exports CALM's files, chosen by format
(`oto arch import --format calm`). The reified model's attributes become framework-neutral
(`external_id`, `external_type`, a `framework` tag, the framework's payload kept as given), so a
node round-trips to the framework it came from and a C4 adapter is a second pack, not a change to
the engine. Nothing in core names CALM.

**A domain feature is a pack plus its tools.** Work and communication, data, policy and the
generated IAM, the domain model, and the factory's engine-side commands move behind their packs.
The engine gains the seams this needs, the only real engineering in the change: a pack's manifest
declares what it provides, and the engine loads it only when the pack is composed in the project.
Five seams: build stages, commands, served endpoints and tools, write hooks before `curate apply`,
`decide` and `promote`, and framework adapters. A pack may depend on another pack (ddd on
architecture, communication on work, policy on data and agent); none may depend on a framework
pack, so the policy pack's generated bindings become a class of its own, and the CALM adapter
exports them as controls when both packs are present.

**What changes for a project.** Nothing at run time: a project on CALM keeps working, with a
migration note for the attribute names, and the roadmap keeps using the work and communication
packs. What changes is what the documents, the command line and the releases say OTO is, and
what a person must touch to swap or extend a framework: a pack, never the engine.

**Order.** The decision and the line in the documents first, with no code moving; then the
seams; then CALM out; then policy and IAM; then the remaining domain tools; then a release with
the migration notes. The roadmap's epics stay as recorded: this decision governs how their
features are packaged, not whether they were delivered.
