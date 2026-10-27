# OTO Factory, the plugin

The software factory on an OTO architecture graph (roadmap Epic J): three agents, one skill, two
hooks, a run snapshot, and a workflow that runs the same hooks in GitHub Actions. The engine writes the spec and the scope; the plugin builds
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

**The spec-context skill** (J3) is what the runner loads first: the run snapshot, the spec as `oto
factory spec` projects it (checked against the snapshot's hash), the criteria `oto factory criteria`
draws, the context's own questions (DD22, DD4, DD5, AR1, AR4, AR10, AR11 through `oto query ask`)
and `arch_context` for the path about to change. A runner starts from the graph, never from loose
files; what the graph does not say is a deviation, never something filled in from memory.

**Both execution environments** (J5). Locally, Claude Code with the plugin installed: the hooks
read `.factory/run.json` in the working directory. In CI, `workflows/oto-factory.yml`, copied to
`.github/workflows/` of the code repository, runs the same plugin through `anthropics/claude-code-action`,
so the same hooks apply: the engine writes the spec, the scope and the criteria from the graph,
starts the run project, the runner builds on a branch, the Stop hook runs the loop to the cap, then
`oto factory run sync` reads the events into the run graph, `status` and `metrics` print it, the
run graph is kept as the workflow's artifact (the audit trail of the run), and a pull request
carries the branch. Nothing is promoted there: a person runs `oto factory run promote`.
`oto init --repo` does not write this workflow; the factory is installed where it is wanted.

**Metrics** (J6) are queries over the run graph: `oto factory run metrics --run <dir> | --runs
<dir> [--json]` gives iterations to pass (mean, min, max over the passed builds), the escalation
rate over the builds that ended, and the iterations where the evaluator and the tests disagreed
(FR4: tests passed, verdict fail; FR5: tests failed, verdict pass), from the `tests` field the
evaluator writes in `verdict.json` and the loop hook carries into the events. Cost is not recorded
by the hooks and the metrics say so; the traces of Epic F hold it.

## The policy snapshot (roadmap E3)

Beside `run.json`, a run may carry `.factory/policy.json`, written by `oto policy snapshot --agent <id>
--principal <id>` from the policy pack's facts: the signed intersection of what the runner (an `Agent`
granted roles) and the identity it runs under (a `Principal` holding roles) may do, with the write
paths it reaches through the code map and the paths it is denied. When the file is there, the guard
reads it through `hooks/policy_snapshot.py` (the same reader the engine plugin carries, byte for
byte) and the policy is the write scope: a write under a denied path is refused naming the rule, a
write under no permitted path is refused naming what is permitted, a snapshot that cannot be read or
trusted blocks every write; `run.json` still says what is read-only, the cap and the iteration. Every
refusal is appended to `.factory/events.jsonl` as `{"event": "denied", ...}`, and `oto factory run
sync` records each one once in the run's audit log (`policy denied`, `refused`).

## Releases

- **0.3.0** (2026-10-27): the policy snapshot (roadmap E3): the guard reads `.factory/policy.json` through
  `hooks/policy_snapshot.py`, the same reader the engine plugin carries, and the policy is the write
  scope; every refusal is an event, and `oto factory run sync` records each once in the run's audit log.
- **0.2.0** (2026-10-26): the spec-context skill; `workflows/oto-factory.yml`, the same hooks in
  GitHub Actions; `verdict.json` carries `tests`, the loop hook carries it into the events, and
  `oto factory run metrics` reads iterations to pass, escalation rate and the disagreements of FR4
  and FR5 from the run graph (factory-run pack release 2). Phase 5 of the roadmap closes here.
- **0.1.0** (2026-10-26): runner, evaluator and aggregator agents; the guard and loop hooks; the run
  snapshot from `oto factory scope`; the run graph and promotion; criteria and deviations.
