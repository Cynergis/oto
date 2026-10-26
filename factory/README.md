# OTO Factory, the plugin

The software factory on an OTO architecture graph (roadmap Epic J, first cut on files): three
agents, two hooks, and a run snapshot. The engine writes the spec and the scope; the plugin builds
and judges inside them.

**Agents.** `factory-runner` builds one component from its spec inside the run's write scope.
`factory-evaluator` judges the result from the spec, the criteria, the code and the test output,
and never from the runner's reasoning: it has no edit tools and writes only `.factory/verdict.json`.
`factory-aggregator` gathers verdicts across a run's components.

**Hooks**, plain Python, no engine on the runner's machine. The PreToolUse guard refuses an edit
outside the run's write scope or inside its read-only paths (`contracts/` by default), and a shell
command that writes a read-only path; with no run in the directory it does nothing; with a snapshot
it cannot read it blocks every write, since an unknown scope contains nothing. The Stop hook runs
the loop: a pass ends it; a fail sends the runner back with the evaluator's gaps; no verdict sends
it to the evaluator; the iteration cap ends the run and escalates it to a person. The loop can be
neither skipped nor run forever.

**The run snapshot**, `.factory/run.json` in the code repository, written by the engine from the
graph's code map:

    oto factory spec component.invoice-intake --out .factory/spec.json --project <graph>
    oto factory scope component.invoice-intake --cap 5 --allow tests/intake --out .factory/run.json --project <graph>

`write_scope` is the component's modules (and what `--allow` adds), `read_only` is `contracts/` (and
what `--read-only` adds), `cap` the iteration cap, `spec_hash` the spec the run builds against. Epic E
replaces the file with a signed policy snapshot; the hooks will read that instead, unchanged in what
they refuse.

**Installing.** The plugin is listed in this repository's marketplace beside the engine's:
`/plugin marketplace add Cynergis/oto`, then `/plugin install oto-factory@cynergis-engine`. It needs
the engine plugin for the graph tools, and a graph with the `architecture` or `ddd` ontology.

What comes next in the roadmap: the spec-context skill (J3), the loop reading the plan and writing
the run graph (J4), both execution environments (J5), metrics (J6), and the release (J7).
