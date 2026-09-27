# Template becomes ontology

Status: in progress on the `ontology` branch, started 2026-09-24. Decided with Chiheb the same day
from the command map (every command, verb and option, and what the change does to each).

The word "template" covered three things: the packaged vocabulary a project starts from, the web
app a project is read with, and a starter gold file. Each gets its own word: **ontology**, **view**,
**start**. "domain" stays reserved for the category an ontology will declare in the packs work; it
already means a relation's domain in the vocabulary language and never names the artefact.

## The command surface

One `oto ontology` holds both families. The rule that keeps fourteen verbs readable: **a verb
with no name acts on the project's ontology; a verb with a name acts on the catalog.**

| Today | Now | |
|---|---|---|
| `oto ontology check\|accept\|rationale\|widen` | same | the project's own vocabulary |
| `oto ontology import --template <name>` | `oto ontology import --from <name>[,<name>]` | `--file` and `--replace` stay |
| `oto templates list\|show\|export\|add\|update\|diff\|plugin` | `oto ontology list\|show\|export\|add\|update\|diff\|plugin` | the catalog |
| `oto templates publish --template <name>` | `oto ontology publish --from <name>` | publish a named one instead of exporting the project |
| `oto templates registry add\|list\|remove\|refresh\|check` | `oto registry add\|list\|remove\|refresh\|check` | its own command: the registry will list packs too |
| `oto init --template <name>` | `oto init --ontology <name>` | several names still merge |
| `oto build --app`, `oto serve --app` | `--view` | the help said "the app template"; the artefact is a view |
| `oto bench template` | `oto bench start` | a starter gold file, a third unrelated meaning |
| `oto templates` | gone | no alias: private, pre-1.0, and the drift tests cover every skill that quoted it |

## The formats

| Where | Before | Now |
|---|---|---|
| The manifest in an ontology directory | `template.json`, field `version` | `manifest.json`, field `release`. `ontology_version` inside `ontology.config.json` is untouched: it rises only on a breaking change, the release on every publish. Changelog entries carry `release`. |
| The pin syntax and the tags | `name@3`, tag `name/v3` | unchanged: the number is the release |
| The project record | `project.config.json` `"template": {…, "version": n}` | `"ontology": {…, "release": n}`; the old key is still read for one release, and `oto status` says so |
| The registry index | `registry.json` `"templates": [{…, "version"}]` | `"ontologies": [{…, "release"}]`; a `packs` array is added later, which is additive |
| On a machine | `~/.oto/templates/`, `OTO_TEMPLATES`, `OTO_TEMPLATE_TOKEN` | `~/.oto/ontologies/`, `OTO_ONTOLOGIES`, `OTO_REGISTRY_TOKEN` |
| In the engine | `oto/templates/`, `model/templates.py`, `template_manifest.py`, `template_compose.py`, `template_registry.py`, `tools/check_templates.py` | `oto/ontologies/`, `model/ontologies.py`, `ontology_manifest.py`, `ontology_compose.py`, `registry.py`, `tools/check_ontologies.py` |
| The site variable in repository mode | `OTO_SITE_APP` | `OTO_SITE_VIEW` |
| A view's own manifest | `app.json` | unchanged for now; the pack contract revisits views |
| The plugin a published ontology carries | skill `<name>-template` | skill `<name>-ontology`, and it quotes the new commands |

## The registry

Cynergis/oto-registry is migrated in place, not republished: the directories, the index key, the
manifests, the plugin skills, the marketplace and the check workflow are regenerated with the
engine's own functions, so no release number moves for a rename. The tags stay.

## Not done here

- "domain" as the category, the pack contract, the catalog page: the packs work.
- A view's `app.json` keeps its name until the pack contract decides what a view carries.
