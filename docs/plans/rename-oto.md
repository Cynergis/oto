# The engine becomes Oto

Status: merged and released as 0.3.0 on 2026-09-24. It is a rename and nothing else: no behaviour
changes, the test suite is the same before and after.

The previous name is deliberately not written in this file. It is a deny term for the
publishability scan, so that it cannot creep back into the code or the docs, and this file is
scanned like any other. Read the "Before" column as the previous name in the same position.

## The names

| Namespace | Before | After | Why |
|---|---|---|---|
| The command and the import | the old command | `oto` | Decided with Chiheb on 2026-09-23. Spelled `oto`, one t. |
| The distribution on the package index | the old name with `-kg` | `oto-kg` | `oto` is taken on the index, as the old name was. Import and distribution stay separate namespaces. |
| The engine repository | the old repository under Cynergis | `Cynergis/oto` | Free on the host. Renamed in place so history, tags and the old URL keep working. |
| The registry repository | the old `-templates` repository under Cynergis | `Cynergis/oto-registry` | The registry will hold both indexes, ontologies and the marketplace, so "templates" was the wrong name. |
| Environment variables and secrets | the old prefix | `OTO_*` | `OTO_DENY_TERMS`, `OTO_ENGINE_TOKEN`, `OTO_SERVE_TOKEN`, `OTO_STORE`, `OTO_TODAY` and the rest. |
| Per-machine state | the dot-directory and dot-files under the old name | `~/.oto`, `.oto-denylist`, `.oto-previous` | Move the directory once; nothing migrates it. |
| The core template | the old `-core` | `oto-core` | Renamed in the engine and in the registry together. |
| Generated workflow files | the old `-checks.yml`, `-ingest.yml`, ... | `oto-checks.yml`, `oto-ingest.yml`, ... | Written by `oto init --repo`; an existing project keeps its old files until it re-runs init. |
| Browser globals in the apps | the old `__*_ADAPT__`, `*Reader`, `*Explorer*` | `window.__OTO_ADAPT__`, `OtoReader`, `OtoExplorer*` | Source and the committed bundle, rebuilt from `ui-src/`. |
| Neo4j constraint names | the old `_entity_key`, ... | `oto_entity_key`, ... | Created with `IF NOT EXISTS`; a store loaded before the rename keeps its old constraints and works. |
| The Claude Code plugin and MCP server | the old name | `oto` | `.claude-plugin/`, `.mcp.json`, `hooks/hooks.json`. |

"Memory Extended" is retired with the old name; Oto is just Oto.

## What is not part of the rename

- **"template" does not become "ontology" here.** That is a concept change, not a rename: the
  `templates` subcommand collides with the existing `ontology` subcommand, the project record is
  keyed `template`, and the registry index has a `templates` array. It is the first item of the
  packs work, where the two subcommands are merged and the registry format is decided once.
- No version bump on the branch. The release commit on `main` bumps to 0.3.0 and tags it.

## After the merge

1. Set the secrets under their new names: `OTO_DENY_TERMS` on both repositories and
   `OTO_ENGINE_TOKEN` on `Cynergis/oto-registry`. Add the old name, and its longer form, to the deny
   terms. Do not add `acme`: it is the placeholder the tests and the sample graphs use.
2. On every machine that used the engine: move the old dot-directory to `~/.oto`, and `uvx` will fetch the new
   distribution on first use.
3. A project in repository mode re-runs `oto init --repo` to get the renamed workflows, or renames
   the files and the secrets by hand.
