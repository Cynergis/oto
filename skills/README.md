# Skills

Playbooks for the steps that need judgment. Each is a `SKILL.md` an agent loads when the task
matches its description.

| Skill | When |
|---|---|
| [concierge](concierge/SKILL.md) | Where the project is, the options at this point, why OTO does what it does, and which playbook to load. Quotes the engine, does no work itself. |
| [build-knowledge-base](build-knowledge-base/SKILL.md) | A folder of documents, all the way to a served graph. Start here. |
| [ontology-interview](ontology-interview/SKILL.md) | Designing or restructuring the vocabulary, with recorded reasoning. |
| [curate](curate/SKILL.md) | One new document or one spoken correction, into the graph under four gates. |
| [vet-provenance](vet-provenance/SKILL.md) | The document set changed; find facts citing a file nobody can open. |
| [query-knowledge](query-knowledge/SKILL.md) | Answer a question: current facts, dated, cited, and what the graph does not know. |
| [evaluate](evaluate/SKILL.md) | A few gold questions per document, run against the graph, judged and recorded. |
| [capture](capture/SKILL.md) | What someone said in conversation, written into the inbox as a dated source document. |
| [act](act/SKILL.md) | Do something about an entity: list the actions the graph declares, confirm before anything that changes the world, invoke through the declared transport with your own tools, record the response as evidence. OTO never invokes. |
| [spec](spec/SKILL.md) | A product spec, ADR or design brief drawn from the graph, every claim cited, and its decisions recorded back as `DecisionRecord` facts ([the convention](spec/references/decisions.md)). |

They are discovered two ways: as a Claude Code plugin (`claude --plugin-dir <this repo>`, via the
manifest in `.claude-plugin/`), or project-locally through the symlinks under `.claude/skills/`
when Claude Code is opened in this repository.

The plugin also registers `oto serve` as an MCP server for whatever project the host opens
(`.mcp.json`), so the `kg_*` tools are available to the agent without editing a config file, and
runs `oto status` at session start (`hooks/hooks.json`) so the agent knows where the project is
before you say anything. Outside an OTO project the server starts and serves nothing, saying so;
in a checkout of a published query store (`oto sync`) both serve and report that store.

A pack (`oto pack`) is the other way in: a plugin published from the registry's marketplace that
carries an ontology, its own skills and its views, and depends on this plugin, so installing a
pack installs the engine with it. Its `start` skill begins a project from the installed copy.

Both run the engine through `uvx`, installing it from the OTO repository on first use and caching
it, so the only prerequisite on a machine is [uv](https://docs.astral.sh/uv/). Nothing has to be
on the PATH and no virtual environment is involved.
