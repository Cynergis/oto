# Factory run — a run's own graph

One OTO project per factory run (roadmap I8, J4): a partition kept in full and never pruned, holding
the `Run` with its plan instance, a `Build` per component with its state (planned, building, passed,
failed, escalated), and every `Iteration` of the loop, numbered, with the verdict that ended the
previous attempt and the gaps the runner was sent back with, each following the last so the run
replays as a walk.

**Written by the engine, never by hand or by a model.** `oto factory run start --plan <plan.json>`
creates the project from the plan `oto factory plan` wrote; the loop hook appends what it decides
to `.factory/events.jsonl` and `oto factory run sync` reads the events in, each recorded once;
`oto factory run record` writes an iteration by hand when there is no hook. Every write is in the
run project's audit log. The graph never goes through the curate gates: it is the engine's record
of what happened, not a claim about the world.

**Only results are promoted.** `oto factory run promote --run <dir> --component <id> --commit <sha>
--into <main project>` writes, for a passed build, a proposal into the main graph: the run as a
document, the evaluator's verdict as evidence of the component, the commit that touches its
modules; that proposal goes through the gates like any other change. Run state stays here.

Questions (FR1 to FR5, awaiting confirmation): the state of each build of a run, the builds
escalated to a person, a build's iterations in order with their verdicts and gaps, and the
iterations where the evaluator and the tests disagreed (FR4: tests passed, verdict fail; FR5: tests
failed, verdict pass). Each `Iteration` carries `tests`, what the tests said beside the verdict, as
the evaluator wrote it in `verdict.json` and the loop hook carried it into the events (release 2).

**Metrics are queries over this graph** (roadmap J6): `oto factory run metrics --run <dir> | --runs
<dir> [--json]` gives iterations to pass (mean, min, max over the passed builds), the escalation rate
over the builds that ended, and the disagreements of FR4 and FR5 with their gaps. Cost is not
recorded by the hooks and is said so, never guessed: the traces of Epic F hold it.

This is a first draft: edit it. The sample is one run of the invoice platform.
