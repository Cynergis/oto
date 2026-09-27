# Packs: the full extension a person installs

Status: phases 1 to 3 delivered and released as 0.5.0 on 2026-09-24; phase 4, the catalog, delivered on the `catalog` branch the same day. Proposed 2026-09-24. Decided with Chiheb on 2026-09-23 and
2026-09-24: a pack is the whole thing a person installs into Claude Code; the ontology inside it
is embedded, with its registry provenance recorded; `app.json` keeps its name; `domain` is the
category, one flat slug, an open list. No plugin registry of our own, no installer of our own.

## The problem

Today an ontology directory becomes a plugin by having a manifest and one generated skill
dropped into it, and the registry's marketplace lists those directories. That mixes the knowledge
model with the thing a person installs. The ontology should stay a vocabulary with what belongs
to a vocabulary. The pack is the extension: the ontology, the skills that know how to use it, the
views that show its graph, and the plugin manifest Claude Code reads.

## A pack directory

    manifest.json               name, release, domain, summary, the ontology it embeds (name,
                                release, registry, source, commit), engine, maintainer, changelog
    .claude-plugin/plugin.json  generated from the manifest: name, version "<release>.0.0",
                                description, author, dependencies ["oto"]
    skills/start/SKILL.md       the starter skill, generated: start a project from the pack, run
                                the interview, hand over; and any skills the author writes beside it
    ontology/<name>/            the embedded ontology, a copy, and beside it every ontology it
                                extends, so the pack composes with nothing else on the machine
    views/<view>/app.json       views, each an app the explorer or the reader can be; optional
    README.md                   generated once, then the author's

The embedded ontology is a copy with provenance, so a pack works with no network and the engine
can still say when the registry holds a newer release of the ontology. The starter skill reaches
it as `${CLAUDE_PLUGIN_ROOT}/ontology`, which Claude Code substitutes inside skill text, so a
project can start from an installed pack without fetching anything:

    oto init --name "<project>" --pack "${CLAUDE_PLUGIN_ROOT}" --project <root>

`dependencies: ["oto"]` makes installing a pack install the engine plugin from the same
marketplace, so the `kg_*` tools and the generic skills come with it.

## What leaves the ontology

An ontology no longer carries `views`, `plugin` or `skills`; `oto ontology plugin` and
`oto ontology publish --plugin` go. An ontology is: vocabulary, rationale, rules, sample, readme,
lexicon, interview, guide, actions, gold. A view that today sits inside a shipped ontology moves
to the pack that ships it. Nothing shipped has one today, so nothing moves.

## The commands

| Command | What it does |
|---|---|
| `oto pack list` | every pack on this machine, and what a registry lists that is not here |
| `oto pack show <name\|dir>` | the manifest, the embedded ontology and whether its registry has a newer release, the skills, the views, the checks |
| `oto pack new <name> --ontology <name\|name@r\|dir> [--domain <slug>] [--summary <text>] [--view <name\|dir>]...` | scaffold a pack under `~/.oto/packs/<name>` (or `--to <dir>`): embed the ontology with provenance, generate the plugin manifest, the starter skill and a README |
| `oto pack check [<dir>]` | the self-check: the manifest, the embedded ontology's own self-check, every view against the embedded vocabulary, a skill per declared skill, the plugin manifest in step with the pack manifest |
| `oto pack refresh [<name\|dir>]` | re-embed the ontology at its registry's current release; regenerate the plugin manifest and the starter skill; the author's skills and views are untouched |
| `oto pack add <name\|name@r\|url>` | fetch a pack from a registry onto this machine, with provenance |
| `oto pack update [<name>]` | re-fetch fetched packs whose registry lists a newer release |
| `oto pack publish --to <registry url> [--from <name\|dir>] [--note <text>]` | copy into `packs/<name>/`, bump the release, regenerate the index and the marketplace, tag, push; refuses on any check or publishability problem |
| `oto init --pack <name\|dir>` | start a project from a pack: its ontology (provenance kept, so `oto ontology diff` works) and its views installed under `<project>/views/` |

The same rule as `oto ontology`: a verb with a name acts on the catalog; `check` and `refresh`
with no name act on the pack in the current directory.

## The registry

    registry.json
      name, summary
      ontologies: [{name, release, domain, summary, path, extends}]
      packs:      [{name, release, domain, summary, path, ontology: {name, release}}]
    <ontology>/                one directory per ontology, as today, without plugin files
    packs/<pack>/              one directory per pack
    .claude-plugin/marketplace.json   generated: the engine plugin `oto` from Cynergis/oto,
                               then every pack as ./packs/<name>
    .github/workflows/oto-registry-check.yml   index matches directories; every ontology and
                               every pack passes its check

Packs live under `packs/` because a pack and the ontology it embeds usually share a name.
The marketplace lists the engine plugin first, as a GitHub source, so one `/plugin marketplace
add Cynergis/oto-registry` gives a person the engine and every pack, and a pack's dependency on
`oto` resolves inside the same marketplace.

Tags: ontologies keep `<name>/v<release>`. A pack is tagged `<name>--v<release>.0.0`, the
convention Claude Code uses to resolve plugin versions, so `/plugin update` and dependency
ranges see the same numbers `oto pack` does.

`oto registry check` covers both lists. `oto ontology publish` stops writing plugin files; the
migration removes the four ontologies' `.claude-plugin` and `skills` from the registry and
creates the four packs in their place, each embedding its ontology at the current release.

## Domain

One optional field, `domain`, on an ontology manifest and on a pack manifest: a lowercase slug.
The index carries it. `oto ontology list` and `oto pack list` group by it when any entry declares
one; `oto ontology show` and `oto pack show` print it once in the header. The self-check accepts
any slug that is well formed and warns on one the engine has not seen; the engine's list starts
from the shipped ontologies (`insurance`, `organization`, `professional-services`, `software`)
and grows when a new one is deliberate. A relation's domain and range are never called anything
else and never appear in the same sentence as the category.

## Phases

| Phase | Delivers | Size |
|---|---|---|
| 1. The pack model | `oto/model/packs.py`: the manifest, `new`, `check`, `refresh`, the generated plugin files moved here from the registry module; `domain` on both manifests; the ontology loses `views`/`plugin`/`skills` | 1 day |
| 2. The catalog and the registry | `oto pack list\|show\|add\|update\|publish`, the `packs` list in the index, the marketplace with the engine plugin first, `oto registry check` over both, the registry migrated in place | 1 day |
| 3. Starting from a pack | `oto init --pack`, views resolved from packs on this machine, the starter skill quoting `${CLAUDE_PLUGIN_ROOT}`; the engine's own plugin manifest brought to the engine's version with `dependencies` empty | half a day |
| 4. The catalog page | `oto registry site`: one page per pack, the ontology drawn by the explorer on the sample, the rationale, the actions, the skills, the views; hosted from the registry by a Pages workflow. Its own branch after this one. | 1 day |

## Not decided here

- Whether a pack may embed more than one ontology. No: one pack, one ontology; a merged
  vocabulary is a project's business, not a pack's.
- Private engine repository and plugin installs: Claude Code clones plugin sources with the
  machine's git credentials; the docs do not say more. The registry stays private until the
  engine is public, so this is the same credential a person already has.
