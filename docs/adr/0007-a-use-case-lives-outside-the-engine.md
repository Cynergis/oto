---
id: ADR-0007
title: A use case of the graph lives outside the engine; the factory is the first
status: accepted
decided_on: 2026-10-28
decided_by: Chiheb Dkhil
governs: [workitem.epic-j]
---

# A use case of the graph lives outside the engine; the factory is the first

## Context

ADR-0006 narrowed OTO's core to the knowledge graph, its tools and its deploy, and made every
domain feature a pack the engine loads only when a project composes it. The engine no longer
imports the factory. It still ships it: the factory-run pack, the pack's code, the oto-factory
Claude Code plugin, its tests, its E2E sections and its rows in the documents all live in the
engine's repository, and a reader of that repository concludes that OTO knows software can be
built from a graph.

It should not. Building software is something one does with a knowledge graph; it is not a
knowledge graph. The same is true of anything that reads the graph to act in the world. OTO's
business ends where the graph is correct, queryable, deployed and governed; what someone builds
on it is theirs, and the engine must not need to know it exists.

## Decision

A use case of the graph lives in a repository of its own, as a pack that carries its vocabulary, its code and its plugin, reaches the engine only through the pack seams, and is listed in the registry; the factory is the first, and the engine's repository forgets it.

## Consequences

**What a use case is.** Anything that reads the graph to act beyond it: a software factory that
builds components from the spec the graph projects, and later whatever else someone writes on the
same seams. Describing the world (the estate, the architecture, the data layer, the people and their
work) and governing the graph (policy on OTO's own writes and reads) are the engine's packs, since
they are about the graph; acting on the world from the graph is a use case.

**What a use case needs from the engine, and has.** The pack seams of ADR-0006, which a pack's
manifest declares: build stages, commands, served endpoints, write, read and status hooks, framework
adapters; and a pack's own `code/` folder, which the engine puts on the import path when it loads
the pack, so a pack installs whole from the user's directory or as a plugin with nothing else on the
machine. A use case imports the engine's public modules (the project, the curate session, the audit
log, the naming helpers, the packs it depends on) and nothing of the engine imports it.

**The factory's repository.** Cynergis/oto-factory holds the oto-factory plugin as a pack: the
plugin manifest, the pack manifest, the factory-run ontology with its code (the spec projection, the
plan, the scope, the run graph, criteria, deviations, metrics and the `factory` command), the
agents, the hooks, the spec-context skill, the Actions workflow, the tests and the E2E section, with
its own CHANGELOG and releases. It is listed in the registry as a plugin with a pinned tag, as
pdf-to-template is, and installed with the plugin command or `oto pack add`. It depends on the
engine's architecture, ddd and policy packs for its inputs and reads the policy's denials through
the policy pack.

**The engine forgets it.** The factory folder, the pack, the code, the tests, the E2E block and the
document rows leave the engine's repository; the engine's marketplace lists the engine plugin alone;
the work pack keeps `oto work event verdict`, which accepts a verdict from any factory, and the
policy pack keeps the snapshot a guard reads, which any guard may read. The engine's CI stops
testing the factory; the factory's CI installs the engine and tests itself against it.

**What stays open.** The two plain-Python guards share one reader, copied into the engine plugin
and the factory plugin byte for byte; with two repositories the factory's CI compares its copy to
the engine's. The factory's contract with the graph (the spec with its hash, the criteria, the run
snapshot, the events file and the verdict) is described in the factory's repository and is what a
second factory would build against; naming it as a contract of its own is the next decision, when
a second one exists.
