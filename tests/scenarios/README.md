# End-to-end scenarios

Each folder is one story of a project being built through the CLI, with what every step must
produce. `tests/test_scenarios.py` plays them; its docstring lists the step kinds.

| Scenario | What it proves |
|---|---|
| `northwind` | The reference path: ingest (a credential blocked, then redacted), survey decisions, a vocabulary from a sheet and an interview, two captures, curate with a value gap fixed and a supersession, build, the competency questions and their history, rules, bench, feedback. |
| `northwind-mistakes` | The gates hold: replays `northwind` to the PM-B change, then an overwrite, a misread number someone said, an undeclared class and relation, a quote from a document the project does not hold, a statement dated by "yesterday", a near name. Each is stopped, and the corrected change passes. |
| `roadmap` | The work and communication packs on this roadmap: an empty `communication` project, the phases and epics drafted from the roadmap document, Epic L deployed by its merged pull requests, Epic B marked deployed by a merged-PR event delivered twice, Epic M blocked on a decision and the person who takes it, the board and the snapshot's `work` section, a message to that person that waits in their inbox, the resolving reply that lifts the block; the board's questions at each step, the block's history as of a date, the published snapshot with the person as initials, and what the commands refuse. |

## Adding one

1. A folder with a `scenario.json`: `name`, `about`, `requires` (modules to skip without), `sources`
   (a Python file whose `make(out)` writes the documents) and `steps`.
2. Author it the way the analyst works: run each step for real, then write down what it produced
   as facts (findings by severity and subject, answer rows, warnings), not whole transcripts.
3. A variant of another scenario starts with `{"replay": "<name>", "through": "<step id>"}`.
4. Keep it deterministic: no model, no network, dates passed with `--at`.
