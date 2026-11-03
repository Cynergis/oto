# OTO commands, by task and by place

Where each command runs, as of OTO 0.16.3. There are three places: **your computer**, a
**workspace sandbox** (kind `ontology`: its folder is a pack in the making, with a `trial/`
knowledge project beside the deliverable) and a **knowledge sandbox** (kind `knowledge`: its folder
is a knowledge project on a released pack). The sandbox skill walks them in that order
([ADR-0012](adr/0012-two-kinds-of-project.md)).

## On your computer

| Task | Commands | Folder |
|---|---|---|
| Make or recreate a sandbox, see where it stands, clean up | `oto sandbox up --kind ontology\|knowledge [--pack <name>] --repo <owner/name> --github-token-env VAR`, `oto sandbox status`, `oto sandbox ls`, `oto sandbox stop <name>`, `oto sandbox rm <name>` | any; `up` lays the project out in `~/<name>/project` before the sandbox exists |
| Know the packs a knowledge sandbox can start from | `oto registry add <url>`, `oto registry list`, `oto registry refresh`, `oto pack list`, `oto pack show <name>`, `oto pack add <name>`, `oto pack update`, `oto pack rm <name>` | any; a pack must be installed here before `sandbox up --pack` |
| Keep a repository publishable | `oto publishable [dir]` | the repository to scan |
| Engine | `oto version` | any |

Claude skills for this place: `sandbox`, `sandboxes`.

## In the workspace sandbox (making an ontology)

| Task | Commands | Folder |
|---|---|---|
| Lay out or open a workspace by hand | `oto pack new <name> --to <dir> [--extends a,b]`, `oto pack new <name> --from-project <dir>` | a new folder of its own |
| Author the vocabulary from questions | the `ontology-interview` skill writes `ontology/<name>/`; by hand `oto ontology check\|accept\|rationale\|widen\|show` against the trial | the workspace root; vocabulary commands take `--project trial` |
| Discover terms from documents | `oto ingest --project trial`, `oto survey --project trial`, `oto figures --project trial` | the trial project |
| Hold the pack to its gates | `oto pack check . --strict`, `oto pack try .`, `oto query --project trial questions` | the workspace root |
| Release | `oto pack publish --from . --to <registry url> --note "..."`, or a tag with the `pack-publish.yml` workflow | the workspace root |
| Re-embed a newer base | `oto pack refresh .` | the workspace root |

## In a knowledge sandbox (building a graph on an ontology)

| Task | Commands | Folder |
|---|---|---|
| Start and orient | `oto init --pack <name> --project <dir>` (done by `sandbox up`), `oto status`, `oto lock`, `oto graph describe\|depend\|dependencies` | the project |
| Bring sources in | `oto ingest run\|complete\|runs`, `oto capture --title --by --at`, `oto clipboard`, `oto survey`, `oto figures` | the project |
| Enter facts through the gates | `oto curate start\|propose\|add\|diff\|check\|apply\|abort\|undo\|assert\|log\|resolve`, `oto draft <slug>`, `oto decide <node> attr=value --by <who>` | the project |
| Words and rules | `oto lexicon suggest\|list\|accept\|reject`, `oto rules check\|diff\|accept\|explain` | the project |
| Keep the vocabulary derived | `oto ontology diff`, `oto ontology update` when the pack has a newer release; `check` and `accept` refuse hand edits | the project |
| Build and verify | `oto build`, `oto clean`, `oto verify`, `oto preview`, `oto vet`, `oto connectors list\|check` | the project |
| Ask and serve | `oto query <entity\|neighbors\|search\|by-type\|count\|group\|stale\|resolve\|docs\|overview\|explain\|policy>`, `oto serve --http 8798` | the project; port 8798 reaches the computer's browser |
| Act on the world | `oto tools list\|check\|show\|record\|runs` | the project |
| Deploy | `oto deploy init\|check\|status`, `oto publish --to <env>`, `oto sync` | the project; the query repository it names |
| Quality and trust | `oto bench start\|add\|validate\|run`, `oto feedback record\|list\|promote`, `oto audit log\|verify\|for <node>` | the project |

Claude skills for this place: `build-knowledge-base`, `curate`, `query-knowledge`, `act`, `start`.
A team that needs a term the pack lacks does not edit the project: it asks for a release in the
workspace sandbox, then runs `oto ontology update` here.

## Outside the map

- `oto ontology list|show|export|add|import|publish`: the older ontology catalog, kept for projects
  that grew a vocabulary of their own (`vocabulary: own`).
- A pack's own commands (`oto arch`, `oto work`, `oto data`, ...) appear only when that pack is
  installed; `oto --help` lists them under *packs*.
