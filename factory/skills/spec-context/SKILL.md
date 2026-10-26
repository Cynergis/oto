---
name: spec-context
description: >-
  Start a factory build from the graph's context, never from loose files: the component's spec as
  `oto factory spec` projects it, the acceptance criteria `oto factory criteria` draws, the context's
  own questions (what the builder must produce, each use case and its scenarios, what the component
  connects to, which budgets it keeps, which contracts it consumes and exposes) and `arch_context`
  for the path about to change. Use at the start of every factory run, and again before an edit
  that reaches outside what the spec named. The runner agent loads it first; a person preparing a
  run reads it to see what the runner will see.
---

# Spec context: what the runner knows before it edits

A runner that starts from a README, a ticket or a chat message builds what the last writer
believed. A runner that starts from the graph builds what the organisation recorded, inside the
scope it declared, against the criteria a person reviewed. This skill is the first thing the runner
does, and it never reads loose files for what the graph can say.

## 1. The run

Read `.factory/run.json`, written by `oto factory scope component.<id> --cap <n> --out .factory/run.json`
from the graph's code map: the component (`component`), its `write_scope` and `read_only` paths, the
`cap`, the `spec_hash`, and the run (`run`) the Stop hook will report to. That is the whole brief
for *where* you may work; the guard hook enforces it, and you do not argue with the guard.

## 2. The spec, as the graph wrote it

    oto factory spec component.<id> --out .factory/spec.json --project <graph>
    oto factory spec --check .factory/spec.json --project <graph>

The spec is JSON the graph projected and hashed: the component as a CALM node, the bounded context
it carries with its use cases, what it exposes and consumes with each contract's version and
status, the requirements with their budgets and the latest measurement, the decisions that govern
it, the controls, the connections, the modules with their last commit, the open change proposals.
`--check` must agree with the `spec_hash` in the run snapshot; if it does not, stop: somebody
edited a spec by hand, and nobody edits a spec, the graph does.

## 3. The criteria, drawn from the graph

    oto factory criteria --component component.<id> --out .factory/criteria --project <graph>

`criteria.md` is what the evaluator judges against: each scenario of the context's use cases as
given, when, then; each business rule; each policy from outside; each budget; each control, every
one naming the nodes it came from. Read it before the code. `criteria.json` is the same for a
program, and `test_criteria_<slug>.py` the skeleton your tests fill in.

## 4. The questions the context answers

Ask them with `oto query ask <ID> <PARAM>=<node> --project <graph>`; each is a question the pack
already holds, so the answer is the graph's, cited and dated:

| Question | What it tells the runner |
|---|---|
| DD22 `CONTEXT=bc.<id>` | What the builder must produce for the context: everything that is part of it. |
| DD4 `USECASE=usecase.<id>` | A use case: who performs it, which commands it issues, which requirement it satisfies, whether it is ready. |
| DD5 `USECASE=usecase.<id>` | Its acceptance scenarios, given, when, then. |
| AR1 `NODE=component.<id>` | What the component connects to, over which protocol, through which interface. |
| AR4 `NODE=component.<id>` | The non-functional requirements it satisfies: metric and budget. |
| AR10 `NODE=component.<id>` | The contracts it consumes, at which version, frozen or draft. |
| AR11 `NODE=component.<id>` | The contracts it exposes, at which version, frozen or draft. |

A frozen contract is read under `contracts/` and never changed: a change is a new version, decided
by a person. A draft contract means the plan would not have scheduled this build yet; if you are
building against one, say so in a deviation rather than guessing its shape.

## 5. `arch_context` before an edit

When the graph is served (`oto serve --project <graph>`), the `arch_context` tool answers for a
path of the code or a node: the requirements with budgets and measured values, the decisions, the
controls on it and on its connections, the modules and their last commit, the open change
proposals. Call it with the path you are about to change, before you change it; the answer is the
same context as the spec, resolved from the file to the component through the code map.

## What you never do

- Read a README, a wiki page, a ticket or a chat log for what the component should do. If the
  graph does not say it, it is a gap in the graph: record it with `oto factory deviate` and let a
  person decide, never fill it in from memory.
- Edit the spec, the criteria or the run snapshot. They are the engine's.
- Carry anything from this context into what the evaluator reads: it judges from the spec, the
  criteria, the code and the tests, never from your account of them.
