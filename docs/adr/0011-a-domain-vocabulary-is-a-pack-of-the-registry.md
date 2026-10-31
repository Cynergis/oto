---
id: ADR-0011
title: A domain vocabulary is a pack of the registry; the engine ships its own vocabulary and no other
status: accepted
decided_on: 2026-10-31
decided_by: Chiheb Dkhil
governs: [workitem.epic-h, workitem.epic-i]
---

# A domain vocabulary is a pack of the registry; the engine ships its own vocabulary and no other

## Context

ADR-0008 moved the first framework to the registry and left one question open: the engine kept
shipping the packs that "describe the world in OTO's own terms", and whether it should was "a
question of distribution, not of what OTO is". ADR-0010 moved the four packs that carry tools and
kept the rest under "what stays": the core's own vocabularies, `oto-core`, the estate (`portfolio`,
`product`, `software-architecture`) and the reified model (`architecture`), "which every pack
extends and the core's own tools read", and the five description packs with no tools of their own
(`agent`, `platform`, `auto-claims`, `organization-process`, `professional-services`).

That leaves ten vocabularies in `oto/ontologies/`. The engine's code depends on one of them.
`oto-core` declares `Graph`, the node every graph holds about itself, which `oto/graphs.py` refuses
to work without; `Tool`, which `oto/tools/model.py` requires of any vocabulary that declares tools;
`Document` and `cites`, which `oto/model/namespaces.py` names; and it is what `oto init` scaffolds
on when no ontology is given, the concierge root among them. No engine module names `product`,
`portfolio` or `software-architecture`; `oto/arch.py` asks the project's vocabulary for `CodeModule`
and `Commit` and points at `architecture` when it lacks them, which is the one tie, and it is a tie
to a command, not to the core. The other nine are domains: what we build, where it runs, who works
on it, a motor claim, an organisation's processes, a consultancy's engagements. They are the first
things a person builds with OTO. They are not OTO.

Shipping them has already cost what ADR-0010 said shipping `ddd` cost. The registry carries seven
of the nine as packs today (`agent`, `auto-claims`, `organization-process`, `platform`, `product`,
`professional-services`, `software-architecture`), published from the engine's copies at some
earlier release and never since: the registry's `product` is at release 9 where the engine ships
14, its `software-architecture` at 10 where the engine ships 12, and every one of them embeds
`oto-core` at 5 where the engine is at 7. Two sources of truth, and the one a project is more likely
to be told to install is the stale one. A project's lock says `origin: built-in` for a vocabulary it
composed, which names an engine release rather than a vocabulary release, so what the project
started from can only be found by knowing which engine wrote it. And a reader of the repository
still finds a `product` and a `professional-services` inside the tool that builds vocabularies, and
cannot tell what OTO is from what it was first used for.

Nothing technical holds them in. An ontology resolves from the user's directory, then the shipped
set, then the packs installed on the machine (`oto/model/ontologies.py`); a pack carries the
vocabularies it extends, so installing it is enough to compose it; `oto registry` fetches a
vocabulary by name from the registries the machine knows; the command, stage, endpoint and hook
seams load a pack's code from its own `code/` (ADR-0010). The sandbox kit installs the engine alone
and the packs skill turns packs on per project. The registry's `pack tests` workflow runs a pack's
tests against the engine.

## Decision

A domain vocabulary is a pack of the registry, released there and installed per project like any pack; the engine ships exactly one vocabulary, `oto-core`, which is its own schema (the temporal fields, `Document`, `Tool`, `Graph`) and not a domain, and the nine domain vocabularies it ships today move to Cynergis/oto-registry, the seven the registry already carries republished from the engine's current releases and `architecture` and `portfolio` published for the first time.

## Consequences

**The engine's vocabulary.** `oto-core` stays in `oto/ontologies/` and is the only entry there: the
schema the engine's code is written against, released with the engine, what `oto init` scaffolds on
with no ontology given and what a concierge root composes. The resolution order keeps a pack's
embedded copy of it from shadowing the engine's. The documents stop calling it "the base every OTO
ontology extends", one of ten, and call it what it is: the engine's own vocabulary, which every
domain vocabulary extends.

**The nine packs.** One release of the registry, before anything leaves the engine, so the registry
is current first and nothing is lost in between: `agent`, `auto-claims`, `organization-process`,
`platform`, `product`, `professional-services` and `software-architecture` republished from the
engine's copies at their current releases, their embedded bases at the engine's current releases;
`portfolio` and `architecture` published as new packs. What a vocabulary carries beside its config
travels with it: `software-architecture`'s tools, `product`'s gold patterns and lexicon, `platform`'s
briefs, the guides and the rules. The dependency chain is the registry's to keep whole:
`portfolio` on `oto-core`, `product` on `portfolio`, `software-architecture` on `product`,
`architecture`, `agent` and `platform` on `software-architecture`, the three others on `oto-core`;
a pack that extends another embeds it, so each installs alone. Each is listed in the index and the
marketplace as `<name>@cynergis`, installed with `/plugin install <name>@cynergis` or `oto pack add`,
and composed with `oto init --ontology <name>` as it was from the engine. From this release the
registry is the only place a domain vocabulary's release is cut.

**The arch command goes with the architecture pack.** ADR-0010 kept `arch` for the core because the
code map, impact and the agent's context are framework-neutral. They are, but they read `CodeModule`,
`Commit`, `Decision` and `Requirement`, which are the architecture vocabulary's, and ADR-0010's own
rule is that the engine ships no command that works only on a pack it does not ship. So `oto arch`
with the code map, compile, impact, measure, import, export and migrate, the `arch_context` tool and
its `/api/arch-context` route, and the `oto architecture` workflow move to the pack's `code/` as the
module `oto_architecture`, through the command seam and a new `tools` seam (`provides.tools`: a
module whose `TOOLS` the server mounts beside its `kg_*` tools when the served project composes the
pack, with the route it answers at and whether `kg_call` may forward it); `oto init --repo` writes
the workflow only when the project composes the pack, and the workflow installs the pack first. This reverses the note in ADR-0010's "what stays";
the adapter seam and the reified model's neutral attributes are unchanged; a framework adapter now
imports the reified model's names from `oto_architecture`, on the path whenever the arch command
loaded it (the calm pack and the plain framework the tests carry do, falling back to the engine's
module on an engine before this decision), and the packs that embed `architecture` re-embed it at
the release that names the pack's code.

**The engine forgets them.** `oto/ontologies/<name>` for the nine leave the repository with their
tests; `oto ontology list` on a bare engine lists `oto-core`; `oto init --ontology <name>` for a name
not on the machine resolves it through the registries the machine knows, as `oto registry fetch`
does, and when it finds none names `oto pack add <name>`; the lock records `origin: pack` or
`fetched` with the release, and `built-in` is only ever `oto-core`. The engine's own tests, which
compose a domain vocabulary to prove what the core does with any vocabulary (the gates, supersession,
federation, the audit, tracing, decisions, the stores), find them under `tests/fixtures/packs`: the
registry's packs, frozen at the release they left the engine with and resolved the way an installed
pack is, so the engine proves itself on the path a project takes, never on a copy it owns; a test
about one pack's own behaviour (the arch command, the code map, `arch_context`, the reified model's
questions) moves beside that pack in the registry, with the plain framework it imports through. The documents name the registry's packs and this decision
where they named the engine's; the roadmap graph records the decision governing Epics H and I.

**The projects that compose them.** The roadmap project composes `portfolio`, `product`,
`software-architecture` and `work`; it installs the packs with `oto pack add`, as the reminder
workflow already does for `work`, and its lock stops saying `built-in`. Northwind composes
`architecture` and `calm`; `architecture` is installed inside its sandbox like `calm` was. The kit
is unchanged: the engine alone, and the packs a project needs turned on from the session.

**The release.** A project that composed a shipped vocabulary must install a pack before the next
engine reads it, which is a change a project notices, so the engine that follows this decision is a
minor release (0.15.0) whose changelog says so and names the one command to run; the engine before
it keeps reading its own copies, as ADR-0010's transition did. The move is one release of the
registry and one pull request of the engine under this decision, then the release; none of it needs
a further decision.

**What stays.** `oto-core`; the gates, the build, the stores and connectors, the estate's graph
commands, the pack and registry commands, the server with its `kg_*` tools, the sandbox and the
kit: the lifecycle of a knowledge graph and its vocabulary, which is what the tool is for. The
registry still carries no engine (ADR-0009).
