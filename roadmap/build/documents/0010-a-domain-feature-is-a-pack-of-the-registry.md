---
id: ADR-0010
title: A domain feature is a pack of the registry; the engine ships no pack with tools of its own
status: accepted
decided_on: 2026-10-30
decided_by: Chiheb Dkhil
governs: [workitem.epic-i, workitem.epic-c, workitem.epic-e, workitem.epic-m, workitem.epic-n]
---

# A domain feature is a pack of the registry; the engine ships no pack with tools of its own

## Context

ADR-0006 drew the line: OTO's core is the knowledge graph's lifecycle with its tools, the estate and
the reified model, and the deploy of the graph; a domain feature is a pack plus its tools, loaded only
when the pack is composed. The seams it asked for exist: a pack's manifest `provides` its commands,
build stages, endpoints, hooks and adapters, the engine reads them from every pack on the machine
(`oto/extensions.py`), and since 0.14.2 a pack's code travels in its own `code/` folder, put on the
import path when the engine loads what the pack provides. ADR-0008 used that seam to move CALM, the
first framework, to the registry, and left one question open: whether the engine keeps shipping the
packs that describe the world in OTO's own terms, "a question of distribution, not of what OTO is".

The engine answers it wrongly today. Four of those packs ship inside the engine's wheel, each with
code of its own: `ddd` with the storming importer and `oto ddd storm`, `work` and `communication`
with the board, the inbox and `oto work`, `data` with lineage, usage and meaning and `oto data`,
`policy` with the compiler, the IAM derivation, two build stages, a write hook and a read hook. The
core names none of them, which is what ADR-0006 asked, but the engine is itself a pack on every
machine, so `oto --help` on a bare install lists `data`, `ddd`, `policy` and `work` under "packs"
as if they were the engine's, and a reader of the repository finds `oto/packs/` and cannot tell what
OTO is from what it also does. The registry already carries `ddd` and `work` as plugins, at older
releases than the engine's copies, so the same vocabulary exists twice and drifts.

Nothing technical holds them in. A command is loaded from the pack's `code/` the way an adapter is.
A pack's tests run in the registry's `pack tests` workflow against the engine. A project that
composes the pack installs it like any other, and the sandbox kit installs the engine alone and lets
the packs skill turn packs on per project.

## Decision

A domain feature is a pack of the registry, its tools in its own `code/` and its tests beside it; the engine ships no pack that provides a command, a build stage or a hook, and `ddd`, the first, moves to Cynergis/oto-registry as the `ddd` pack.

## Consequences

**The ddd pack.** `packs/ddd` in the registry, the pack that already existed, brought to the engine's
line: the `ddd` ontology at release 2 (on `architecture`, as roadmap I1 decided), the storming
importer and the `ddd` command as the module `oto_ddd` in its `code/`, the ontologies it extends
embedded at their current releases, the `model-domain` skill and the domain-model view it already
carried, and the engine's ddd tests moved beside it with the plain framework fixture they need. It is
listed as `ddd@cynergis`, installed with `/plugin install ddd@cynergis` or `oto pack add ddd`, and
`oto init --ontology ddd` composes it from the pack as it did from the engine. On an engine that
still ships `ddd` the engine's copy is read and the pack's code is never loaded; from the engine that
follows this decision the pack is the only `ddd` there is.

**The engine forgets it.** `oto/packs/ddd` and `oto/ontologies/ddd` leave the engine's repository
with their two test files; no shipped manifest provides a `ddd` command; `oto --help` on a bare engine
no longer lists `ddd`; the engine's own tests that composed `ddd` to prove a composition rule use
another shipped pattern pack (`agent`) or another decision attribute (`data`'s); the documents name the
registry's pack and this decision where they named the engine's; the roadmap graph records the
decision governing Epic I and the epics whose packs follow.

**What follows, in order.** `work` with `communication` (the roadmap project and the reminder
workflow compose it, so the engine's CI installs the pack), then `data` (the connectors stay core, the
publish uses them), then `policy` (its hooks and the snapshot reader the factory shares are the most
entangled). Each is a release of the registry's pack and a pull request of the engine, under this
decision; none needs a new one.

**What stays.** The core's own vocabularies: `oto-core`, the estate (`portfolio`, `product`,
`software-architecture`) and the reified model (`architecture`), which every pack extends and the
core's own tools read. The `arch` command is the core's (the code map, impact, the agent's context
are framework-neutral, ADR-0006), so it belongs in the core's command list rather than in the
architecture manifest's `provides`; that correction is a consequence of this decision, made when the
manifest is next touched. The description packs with no tools of their own (`agent`, `platform`,
`auto-claims`, `organization-process`, `professional-services`) stay the distribution question
ADR-0008 left open: nothing in this decision moves them.
