---
id: ADR-0009
title: The registry carries extensions and packs; the engine comes from its own marketplace
status: accepted
decided_on: 2026-10-29
decided_by: Chiheb Dkhil
governs: [workitem.epic-l]
---

# The registry carries extensions and packs; the engine comes from its own marketplace

## Context

The registry, Cynergis/oto-registry, listed the engine plugin `oto` among its plugins, pinned to the
engine's release tag, so that every pack's dependency on `oto` resolved inside one marketplace. The
engine's release workflow moved that pin on every tag, through a pull request the registry's owner
merged by hand, and the engine's own marketplace (`cynergis-engine`, in its repository) listed the
engine as well: two places said which engine a person installs, and the registry's one was always a
merge behind.

The registry is OTO's catalog of what extends the engine: ontologies, packs, and the plugins built on
the engine that live in their own repositories. The engine is not an extension of itself. A person
who adds the registry to Claude Code should find there what they add to OTO, and find OTO where OTO
lives.

Claude Code resolves a plugin's dependency against the plugin's own marketplace, and lets a
marketplace allow a dependency to cross into another one it names
(`allowCrossMarketplaceDependenciesOn`); a dependency the person has already installed is accepted
either way.

## Decision

The engine plugin is installed from the engine repository's own marketplace, `cynergis-engine`; a registry carries extensions and packs of the engine and never the engine itself, and every pack names the engine as `oto@cynergis-engine`, which the registry's marketplace allows to cross.

## Consequences

**The engine.** `oto pack new` and `oto pack publish` write `dependencies: ["oto@cynergis-engine"]`
in a pack's plugin manifest; `oto pack check` accepts the bare `oto` of packs written before, and
names the new form. A registry's marketplace lists its plugins and its packs and carries
`allowCrossMarketplaceDependenciesOn: ["cynergis-engine"]`; a registry whose index names `oto`
among its plugins (one under test, from a branch) still lists the engine from there, and allows
nothing. The release workflow no longer pins the engine into the registry; `registry-pin.yml` stays
for the plugins the registry lists from their own repositories. `oto lock` finds the engine plugin in
whichever marketplace Claude Code knows that lists it, the engine's own first. The repository
workflows the engine writes, the kit, the catalog pages and the documents install the engine from
its marketplace before the packs: `/plugin marketplace add Cynergis/oto`, `/plugin install
oto@cynergis-engine`, then the registry.

**The registry.** The `oto` entry leaves its index and its marketplace; every pack's manifest names
`oto@cynergis-engine`; the README says to add the engine's marketplace first. The plugins the
registry lists from their own repositories (oto-factory, pdf-to-template) name the engine the same
way in their repositories, and their Actions workflows add both marketplaces.

**What a person does once.** On a machine that installed `oto@cynergis`: add the engine's
marketplace, install `oto@cynergis-engine`, uninstall `oto@cynergis`; a project's
`.claude/settings.json` names the new id and both marketplaces, and `oto lock` records it. The kit
does this for a new sandbox; an existing sandbox runs the same three commands.

**What stays open.** Whether the engine keeps shipping copies of the description packs the registry
also carries (ADR-0008 left it open) is still open; this decision is about where the engine itself
comes from, not about the packs.
