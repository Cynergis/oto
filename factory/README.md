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

**The run graph.** Each decision of the Stop hook is appended to `.factory/events.jsonl` beside the
snapshot (`run.json` names the run under `"run"`), and `oto factory run sync --run <run project>
--events .factory/events.jsonl` reads it into the run's own graph, one OTO project per run that
`oto factory run start --plan <plan.json>` made; `status` and `replay` read it back, and `oto
factory run promote` proposes a passed build's verdict and commit into the main graph through its
gates. Run state never enters the main graph.

**Criteria and deviations.** `oto factory criteria --context <id> --out <dir>` draws `criteria.md`, `criteria.json`
and a pytest skeleton from the graph (the scenarios, rules, policies, budgets and controls of a context, each
tracing to its nodes) for the evaluator to judge against; `oto factory deviate --run <dir> --component <id>
--about <node> --observed ... --proposes ... --into <main project>` records what a runner or the evaluator
found impossible as specified as a change proposal in the main graph, names the siblings reached through the
contract, and fails the build until a person decides.

What comes next in the roadmap: the spec-context skill (J3), both execution environments (J5), metrics (J6), and the release (J7).
